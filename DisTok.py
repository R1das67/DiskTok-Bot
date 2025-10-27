import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import os

# -------------------------
# Tokens aus Railway-Umgebungsvariablen
# -------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "tiktok-scraper-api2.p.rapidapi.com"

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
# Prüft, ob Nutzer Admin ist
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
# Slash Command: /config-distok-list
# -------------------------
@bot.tree.command(name="config-distok-list", description="Verwalte TikTok-User + Channels (Admin-only)")
@app_commands.describe(
    action="add / remove / edit / list",
    index="Index zum Bearbeiten/Löschen (1-10)",
    username="TikTok Benutzername (ohne @)",
    channel="Discord-Kanal (#channel)"
)
async def config_distok_list(interaction: discord.Interaction, action: str, index: int = None, username: str = None, channel: discord.TextChannel = None):
    if not is_admin(interaction) and action != "list":
        await interaction.response.send_message("❌ Nur Admins können diese Aktion ausführen.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    guild = data["guilds"].setdefault(guild_id, {"distok_list": []})
    distok_list = guild["distok_list"]

    action = action.lower()
    if action == "add":
        if len(distok_list) >= 10:
            await interaction.response.send_message("❌ Maximal 10 Einträge erlaubt.", ephemeral=True)
            return
        if not username or not channel:
            await interaction.response.send_message("❌ Bitte gib einen TikTok-Benutzernamen und einen Kanal an.", ephemeral=True)
            return
        distok_list.append({"username": username, "channel_id": channel.id, "last_video": None})
        save_data(data)
        await interaction.response.send_message(f"✅ Eintrag hinzugefügt: `{username}` → {channel.mention}", ephemeral=True)

    elif action == "remove":
        if not index or index < 1 or index > len(distok_list):
            await interaction.response.send_message("❌ Ungültiger Index.", ephemeral=True)
            return
        removed = distok_list.pop(index - 1)
        save_data(data)
        await interaction.response.send_message(f"🗑️ Eintrag entfernt: `{removed['username']}`", ephemeral=True)

    elif action == "edit":
        if not index or index < 1 or index > len(distok_list):
            await interaction.response.send_message("❌ Ungültiger Index.", ephemeral=True)
            return
        if not username and not channel:
            await interaction.response.send_message("❌ Bitte gib entweder einen neuen Benutzernamen oder Kanal an.", ephemeral=True)
            return
        entry = distok_list[index - 1]
        if username:
            entry["username"] = username
        if channel:
            entry["channel_id"] = channel.id
        save_data(data)
        await interaction.response.send_message(f"✏️ Eintrag aktualisiert: `{entry['username']}` → <#{entry['channel_id']}>", ephemeral=True)

    elif action == "list":
        if not distok_list:
            await interaction.response.send_message("📭 Keine TikTok-User/Channels eingetragen.", ephemeral=True)
            return
        msg = "**__DisTok List__**\n"
        for i, entry in enumerate(distok_list, start=1):
            ch = interaction.guild.get_channel(entry["channel_id"])
            ch_mention = ch.mention if ch else f"ChannelID {entry['channel_id']}"
            msg += f"{i}. Tiktokuser: `{entry['username']}`    Tiktokchannel: {ch_mention}\n"
        await interaction.response.send_message(msg, ephemeral=True)

    else:
        await interaction.response.send_message("❌ Ungültige Aktion. Nutze add / remove / edit / list.", ephemeral=True)

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
        for entry in guild_data.get("distok_list", []):
            try:
                latest = await get_latest_tiktok(entry["username"])
                if not latest:
                    continue

                last_video_id = entry.get("last_video")
                if last_video_id != latest["video_id"]:
                    entry["last_video"] = latest["video_id"]
                    save_data(data)

                    channel = bot.get_channel(entry["channel_id"])
                    if not channel:
                        continue

                    message = (
                        f"**__Neues Tiktokvideo von {entry['username']}__**\n"
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
                print(f"⚠️ Fehler bei {entry['username']}: {e}")

# -------------------------
bot.run(TOKEN)
