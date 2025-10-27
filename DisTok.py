import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import os
from dotenv import load_dotenv

# Lade .env (Discord Token + RapidAPI Key)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "tiktok-scraper-api2.p.rapidapi.com"  # Je nach API ggf. anpassen

# -------------------------
# Discord Setup
# -------------------------
intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
DATA_FILE = "data.json"

# -------------------------
# Daten laden/speichern
# -------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"guilds": {}}
    with open(DATA_FILE, "r", encoding="utf8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2)

data = load_data()

# -------------------------
# Prüft ob Nutzer Admin ist
# -------------------------
def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

# -------------------------
# Events
# -------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot online als {bot.user}")
    check_tiktok.start()

# -------------------------
# Slash Commands (Admin Only)
# -------------------------

# /setchannel
@bot.tree.command(name="setchannel", description="Setzt den Kanal für TikTok-Benachrichtigungen. (Nur Admins)")
@app_commands.describe(channel="Kanal, in den der Bot TikTok-Nachrichten posten soll")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Administratoren können diesen Befehl nutzen.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    if guild_id not in data["guilds"]:
        data["guilds"][guild_id] = {"channel_id": None, "tiktok_users": {}}

    data["guilds"][guild_id]["channel_id"] = channel.id
    save_data(data)
    await interaction.response.send_message(f"✅ Kanal gesetzt: {channel.mention}", ephemeral=True)

# /settiktokname
@bot.tree.command(name="settiktokname", description="Fügt einen TikTok-Benutzer hinzu, der überwacht werden soll. (Nur Admins)")
@app_commands.describe(username="TikTok-Benutzername (ohne @)")
async def settiktokname(interaction: discord.Interaction, username: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Administratoren können diesen Befehl nutzen.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    guild = data["guilds"].setdefault(guild_id, {"channel_id": None, "tiktok_users": {}})

    if username in guild["tiktok_users"]:
        await interaction.response.send_message("❗Dieser TikTok-Benutzer wird bereits überwacht.", ephemeral=True)
        return

    guild["tiktok_users"][username] = {"last_video": None}
    save_data(data)
    await interaction.response.send_message(f"✅ TikTok-Account `{username}` hinzugefügt.", ephemeral=True)

# /removetiktokname
@bot.tree.command(name="removetiktokname", description="Entfernt einen TikTok-Benutzer aus der Überwachungsliste. (Nur Admins)")
@app_commands.describe(username="TikTok-Benutzername (ohne @)")
async def removetiktokname(interaction: discord.Interaction, username: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Administratoren können diesen Befehl nutzen.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    guild = data["guilds"].get(guild_id)

    if not guild or username not in guild["tiktok_users"]:
        await interaction.response.send_message("❌ Dieser TikTok-Benutzer wird nicht überwacht.", ephemeral=True)
        return

    del guild["tiktok_users"][username]
    save_data(data)
    await interaction.response.send_message(f"🗑️ TikTok-Account `{username}` entfernt.", ephemeral=True)

# /listtiktok (Darf jeder sehen)
@bot.tree.command(name="listtiktok", description="Listet alle aktuell überwachten TikTok-Accounts auf.")
async def listtiktok(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    guild = data["guilds"].get(guild_id)

    if not guild or not guild["tiktok_users"]:
        await interaction.response.send_message("📭 Keine TikTok-Accounts eingetragen.", ephemeral=True)
        return

    users = "\n".join([f"• `{u}`" for u in guild["tiktok_users"].keys()])
    await interaction.response.send_message(f"👀 Überwachte TikTok-Accounts:\n{users}", ephemeral=True)

# -------------------------
# TikTok-Abfrage über RapidAPI
# -------------------------
async def get_latest_tiktok(username: str):
    url = f"https://tiktok-scraper-api2.p.rapidapi.com/user/posts?username={username}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data_resp = await response.json()
            videos = data_resp.get("data", {}).get("videos", [])
            if not videos:
                return None
            video_id = videos[0]["id"]
            video_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
            return {"video_id": video_id, "url": video_url}

# -------------------------
# Hintergrundloop (alle 5 Minuten)
# -------------------------
@tasks.loop(minutes=5)
async def check_tiktok():
    print("🔁 Überprüfe TikTok-Accounts ...")
    for guild_id, guild_data in data["guilds"].items():
        channel_id = guild_data.get("channel_id")
        if not channel_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for username, info in guild_data.get("tiktok_users", {}).items():
            try:
                latest = await get_latest_tiktok(username)
                if not latest:
                    continue

                last_video_id = info.get("last_video")
                if last_video_id != latest["video_id"]:
                    info["last_video"] = latest["video_id"]
                    save_data(data)

                    message = (
                        f"**__Neues Tiktokvideo von {username}__**\n"
                        f"**Ihr wisst alle was zutun ist!**\n"
                        f"> **Das Video liken ❤️**\n"
                        f"> **Einen netten Kommentar schreiben ⌨️**\n"
                        f"> **Das Video teilen ↪️**\n"
                        f"> **Und dem Benutzer folgen ➕**\n"
                        f"|| @everyone ||\n"
                        f"** {latest['url']} **"
                    )
                    await channel.send(message)
            except Exception as e:
                print(f"⚠️ Fehler bei {username}: {e}")

# -------------------------
bot.run(TOKEN)