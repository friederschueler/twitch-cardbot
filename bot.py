import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from twitchio.ext import commands
from fastapi import FastAPI, Request
import uvicorn
import threading

from config import OAUTH_URL, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, CHANNEL_NAME

# OAuth-Token-Variable
oauth_token: str = ""


def init_db():
    """ Datenbank initialisieren """
    conn = sqlite3.connect('cards.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_cards (
            user TEXT PRIMARY KEY,
            card_name TEXT,
            scryfall_link TEXT
        )
    ''')
    conn.commit()
    conn.close()


def set_user_card(user, card_name, scryfall_link):
    """ Karteninformationen in die Datenbank speichern """
    conn = sqlite3.connect('cards.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO user_cards (user, card_name, scryfall_link) VALUES (?, ?, ?)
    ''', (user, card_name, scryfall_link))
    conn.commit()
    conn.close()


def get_user_card(user):
    """ Karteninformationen aus der Datenbank abrufen """
    conn = sqlite3.connect('cards.db')
    c = conn.cursor()
    c.execute('SELECT card_name, scryfall_link FROM user_cards WHERE user = ?', (user,))
    result = c.fetchone()
    conn.close()
    return result


def get_card_name(scryfall_link):
    """ Funktion zum Abrufen des Kartennamens von Scryfall """
    response = requests.get(scryfall_link)
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, 'html.parser')
    card_name_tag = soup.find('meta', property='og:title')
    if not card_name_tag:
        return None
    card_name = card_name_tag['content']
    return card_name


def search_card(number_or_name, set_code):
    """ Scryfall-Suche nach Kartennummer und Set oder Kartenname und Set """
    if number_or_name.isdigit():
        search_url = f"https://scryfall.com/search?q=number%3A{number_or_name}+s%3A{set_code}"
    else:
        search_url = f"https://scryfall.com/search?q=name%3A{number_or_name}+s%3A{set_code}"

    response = requests.get(search_url)
    if response.status_code != 200:
        return None, None
    soup = BeautifulSoup(response.text, 'html.parser')
    card_link_tag = soup.find('a', class_='card-grid-item-card')
    if not card_link_tag:
        return None, None
    card_link = f"https://scryfall.com{card_link_tag['href']}"
    card_name = get_card_name(card_link)
    return card_name, card_link


class Bot(commands.Bot):
    """ Twitch-Bot-Klasse """

    def __init__(self, token: str) -> None:
        super().__init__(token=token, prefix='!', initial_channels=[CHANNEL_NAME])
        init_db()

    async def event_ready(self):
        print(f'Logged in as {self.nick}')

    @commands.command(name='setcard')
    async def setcard(self, ctx, user: str, *args):
        if ctx.author.is_mod:
            if len(args) == 1 and args[0].startswith("http"):
                scryfall_link = args[0]
                card_name = get_card_name(scryfall_link)
                if card_name:
                    set_user_card(user, card_name, scryfall_link)
                    await ctx.send(f'{ctx.author.name}, die Karte für {user} wurde auf {card_name} gesetzt.')
                else:
                    await ctx.send(f'{ctx.author.name}, konnte den Kartennamen nicht von {scryfall_link} abrufen.')
            elif len(args) == 2:
                identifier, set_code = args
                card_name, scryfall_link = search_card(identifier, set_code)
                if card_name and scryfall_link:
                    set_user_card(user, card_name, scryfall_link)
                    await ctx.send(f'{ctx.author.name}, die Karte für {user} wurde auf {card_name} gesetzt.')
                else:
                    await ctx.send(
                        f'{ctx.author.name}, konnte keine eindeutige Karte für {identifier} in Set {set_code} finden.')
            else:
                await ctx.send(
                    f'{ctx.author.name}, ungültige Argumente für !setcard. Benutze entweder einen Scryfall-Link oder eine Kartennummer/einen Kartennamen und ein Set-Kürzel.')
        else:
            await ctx.send(f'{ctx.author.name}, nur Mods können diesen Befehl verwenden.')

    @commands.command(name='card')
    async def card(self, ctx):
        user = ctx.author.name
        card = get_user_card(user)
        if card:
            card_name, scryfall_link = card
            await ctx.send(f'{user}, deine Karte ist {card_name}: {scryfall_link}')
        else:
            await ctx.send(f'{user}, du hast noch keine Karte gesetzt.')


# FastAPI-Anwendung
app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Twitch OAuth2.0 Authorization"}


@app.get("/authorize")
async def authorize():
    return {"authorization_url": OAUTH_URL}


@app.get("/callback")
async def callback(request: Request):
    global oauth_token
    code = request.query_params.get('code')
    if code:
        token_url = 'https://id.twitch.tv/oauth2/token'
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': REDIRECT_URI
        }
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            oauth_token = response.json()['access_token']
            return {"message": "Authorization successful", "token": oauth_token}
    return {"message": "Authorization failed"}


def run_bot():
    global oauth_token
    while not oauth_token:
        time.sleep(0.01)  # Warte, bis das Token verfügbar ist
    bot = Bot(token=oauth_token)
    bot.run()


def run_server():
    uvicorn.run(app, host="0.0.0.0", port=8008)


if __name__ == "__main__":
    # Starte FastAPI-Server
    server_thread = threading.Thread(target=run_server)
    server_thread.start()
    # Öffne den Browser zur Autorisierung
    import webbrowser

    webbrowser.open(OAUTH_URL)
    # Starte den Bot
    run_bot()
