"""
Discord bot for Story Finder

Configuration (environment variables):
    DISCORD_TOKEN   Discord bot token (required)
    OWNER_ID        Your Discord user ID; restricts /reindex access (optional)
    MIN_SCORE       Minimum match score (default 0.35; tune for your channel)

Run:
    python bot.py
"""
import asyncio
import os
import sys
from pathlib import Path

import discord
from discord import app_commands

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import finder
except ModuleNotFoundError:
    import Finder as finder


def _safe_int_env(name: str, default: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _safe_float_env(name: str, default: float = 0.35) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is required. "
        "Set it in PowerShell with: $env:DISCORD_TOKEN='your_bot_token_here'"
    )

OWNER_ID = _safe_int_env("OWNER_ID", 0)
MIN_SCORE = _safe_float_env("MIN_SCORE", 0.35)

# Limit concurrent embedding jobs to prevent overload when multiple users search.
search_slots = asyncio.Semaphore(2)


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Load the model in advance so the first command is faster.
        await asyncio.to_thread(finder.get_model)
        await self.tree.sync()


client = Bot()


def fmt_time(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


@client.tree.command(name="find", description="Find matching clips from a story summary")
@app_commands.describe(summary="A remembered story summary; more detail improves matches", top="Number of results (1-10)")
async def find(
    interaction: discord.Interaction,
    summary: app_commands.Range[str, 10, 2000],
    top: app_commands.Range[int, 1, 10] = 5,
):
    status_message = f"Searching for clips matching: {summary}"
    await interaction.response.send_message(status_message)

    async with search_slots:
        results = await asyncio.to_thread(finder.search, summary, top)

    if not results or results[0]["score"] < MIN_SCORE:
        await interaction.edit_original_response(
            content=(
                f"{status_message}\n\n"
                "No close match found. Try adding details such as characters, locations, or key events."
            )
        )
        return

    embed = discord.Embed(title="Likely matches", color=discord.Color.dark_purple())
    embed.set_thumbnail(url=f"https://img.youtube.com/vi/{results[0]['video_id']}/hqdefault.jpg")
    embed.set_footer(text=f"Search query: {summary[:80]}{'…' if len(summary) > 80 else ''}")

    for i, r in enumerate(results, 1):
        snippet = r["snippet"][:160].replace("\n", " ")
        embed.add_field(
            name=f"{i}. {r['title']}"[:256],
            value=(
                f"Similarity **{r['score']:.0%}** · "
                f"[Watch matching moment ({fmt_time(r['start'])})]({r['url']})\n> {snippet}…"
            )[:1024],
            inline=False,
        )

    await interaction.edit_original_response(content=status_message, embed=embed)


@client.tree.command(name="reindex", description="(Bot owner) Update the index from a channel")
@app_commands.describe(channel_url="YouTube channel URL", limit="Number of recent videos to check")
async def reindex(interaction: discord.Interaction, channel_url: str, limit: int = 20):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("This command is for the bot owner only.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)
    added = await asyncio.to_thread(
        finder.index_channel, channel_url, False, limit, lambda m: print(m)
    )
    await interaction.followup.send(f"Done. Added {added} new video(s).")


try:
    client.run(TOKEN)
except discord.errors.LoginFailure:
    print("\nDiscord login failed: the token is invalid or expired.")
    print("Create a bot token in the Discord Developer Portal and set it again:")
    print("  $env:DISCORD_TOKEN='your_bot_token_here'")
    print("Then run: python bot.py\n")
    raise SystemExit(1)
