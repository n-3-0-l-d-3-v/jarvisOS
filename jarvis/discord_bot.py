import discord
from discord.ext import commands
import asyncio
import json
from datetime import datetime
from pathlib import Path

from jarvis.config import (
    DISCORD_BOT_TOKEN,
    DISCORD_CHANNEL_ID,
    REPO_PATH,
    INDEX_PATH,
)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def send_response(channel, title, description, color=discord.Color.green()):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Jarvis Knowledge OS")
    await channel.send(embed=embed)


def is_youtube_url(text: str) -> bool:
    t = text.lower()
    return "youtube.com" in t or "youtu.be" in t


def is_article_url(text: str) -> bool:
    t = text.strip()
    if not (t.startswith("http://") or t.startswith("https://")):
        return False
    return not is_youtube_url(t)


@bot.event
async def on_ready():
    print(f"  [Discord] Jarvis bot online: {bot.user}")
    print(f"  [Discord] Watching channel: {DISCORD_CHANNEL_ID}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # If channel ID configured, restrict to that channel
    if DISCORD_CHANNEL_ID and str(message.channel.id) != DISCORD_CHANNEL_ID:
        return

    content = message.content.strip()
    if not content:
        return

    timestamp = datetime.now().isoformat()

    # show processing reaction
    try:
        await message.add_reaction("⏳")
    except Exception:
        pass

    result = None

    try:
        # Help command
        if content.lower() in ["!help", "help", "?", "!commands"]:
            await send_response(
                message.channel,
                "Jarvis Commands",
                "**Just send:**\n" "• Any text → saves as a note\n" "• YouTube URL → saves as video summary\n" "• Any article URL → saves as article note\n" "• `LC-76 ...` → saves as DSA note\n\n" "**Special prefixes:**\n" "• `bug: ...` → saves as bug note\n" "• `snippet: ...` → saves as code snippet\n\n" "**Commands:**\n" "• `!status` → show repo stats\n" "• `!today` → show today's captures\n" "• `!dsa` → show DSA progress",
                color=discord.Color.blue(),
            )
            await message.remove_reaction("⏳", bot.user)
            await message.add_reaction("✅")
            return

        if content.lower() == "!status":
            index_data = json.loads(INDEX_PATH.read_text())
            total = index_data.get("total_notes", 0)
            await send_response(
                message.channel,
                "Jarvis Status",
                f"📚 Total notes: **{total}**\n" f"📅 Today: checking...\n" f"🔗 GitHub: synced",
                color=discord.Color.blue(),
            )
            await message.remove_reaction("⏳", bot.user)
            await message.add_reaction("✅")
            return

        if content.lower() == "!today":
            from datetime import date

            today = date.today().isoformat()
            index_data = json.loads(INDEX_PATH.read_text())
            notes = index_data.get("notes", [])
            today_notes = [n for n in notes if n.get("date") == today]

            if today_notes:
                note_list = "\n".join([
                    f"• {n.get('title','?')[:50]} [{n.get('type','?')}]" for n in today_notes[:10]
                ])
                desc = f"**{len(today_notes)} notes captured today:**\n{note_list}"
            else:
                desc = "No notes captured today yet."

            await send_response(message.channel, f"Today — {today}", desc, color=discord.Color.blue())
            await message.remove_reaction("⏳", bot.user)
            await message.add_reaction("✅")
            return

        if content.lower() == "!dsa":
            index_data = json.loads(INDEX_PATH.read_text())
            notes = index_data.get("notes", [])
            dsa_notes = [n for n in notes if n.get("type") == "dsa"]
            patterns = {}
            for n in dsa_notes:
                p = n.get("dsa_pattern", "arrays")
                patterns[p] = patterns.get(p, 0) + 1

            pattern_list = "\n".join([f"• {p}: **{c}** notes" for p, c in sorted(patterns.items())])
            await send_response(
                message.channel,
                f"DSA Progress — {len(dsa_notes)} problems",
                pattern_list or "No DSA notes yet.",
                color=discord.Color.gold(),
            )
            await message.remove_reaction("⏳", bot.user)
            await message.add_reaction("✅")
            return

        # Route: YouTube URL
        if is_youtube_url(content):
            await message.channel.send("📹 YouTube URL detected — fetching transcript and summarizing...")
            from jarvis.youtube_agent import process_youtube_url

            result = await asyncio.get_event_loop().run_in_executor(None, process_youtube_url, content, timestamp)
            if result:
                await send_response(
                    message.channel,
                    "✅ Video Captured",
                    f"**{result['title'][:60]}**\nChannel: {result['channel']}\nSaved: `{result['folder_path']}/`\nGitHub: pushed ✓",
                    color=discord.Color.green(),
                )
            else:
                await send_response(message.channel, "❌ Video Failed", "Could not process YouTube video.", color=discord.Color.red())

        # Route: Article URL
        elif is_article_url(content):
            await message.channel.send("📄 Article URL detected — fetching and summarizing...")
            from jarvis.article_fetcher import process_article_url

            result = await asyncio.get_event_loop().run_in_executor(None, process_article_url, content, "", timestamp)
            if result:
                await send_response(
                    message.channel,
                    "✅ Article Captured",
                    f"**{result['title'][:60]}**\nSite: {result['site']}\nSaved: `{result['folder_path']}/`\nGitHub: pushed ✓",
                    color=discord.Color.green(),
                )
            else:
                await send_response(message.channel, "❌ Article Failed", "Could not fetch article.", color=discord.Color.red())

        # Regular text note
        else:
            await message.channel.send("💭 Processing note...")
            from jarvis.capture import capture_note
            from jarvis.capture import mark_processed
            from jarvis.orchestrator import process_single_note
            from jarvis.git_sync import sync, build_commit_message

            source = "discord"
            if content.lower().startswith("lc-") or content.lower().startswith("leetcode"):
                source = "leetcode"
            elif content.lower().startswith("bug:"):
                source = "cli"

            inbox_file = capture_note(text=content, source=source, source_url="", extra={"origin": "discord"})

            result_data = await asyncio.get_event_loop().run_in_executor(
                None, process_single_note, inbox_file, False
            )

            if result_data.get("success"):
                try:
                    mark_processed(inbox_file)
                except Exception as exc:
                    print(f"  [Discord] Failed to mark inbox file processed: {exc}")

                classification = result_data.get("classification") or {}
                commit_message = build_commit_message(classification, result_data.get("text", content))
                await asyncio.get_event_loop().run_in_executor(None, sync, commit_message)

                index_data = json.loads(INDEX_PATH.read_text())
                notes = index_data.get("notes", [])
                if notes:
                    last_note = notes[-1]
                    await send_response(
                        message.channel,
                        "✅ Note Captured",
                        f"**{last_note.get('title','?')[:60]}**\nDomain: {last_note.get('domain','?')}\nType: {last_note.get('type','?')}\nSaved: `{last_note.get('folder_path','?')}/`\nGitHub: pushed ✓",
                        color=discord.Color.green(),
                    )
            else:
                error_msg = result_data.get("error", "Unknown error")
                print(f"  [Discord] Note processing failed: {error_msg}")
                await send_response(message.channel, "⚠️ Note Saved to Inbox", f"Captured but processing had issues.\nError: {error_msg}\nRun `jar process` to retry.", color=discord.Color.orange())

        # Auto-sync after any successful operation
        if result:
            from jarvis.git_sync import sync
            await asyncio.get_event_loop().run_in_executor(None, sync, "feat: discord capture sync")

    except Exception as e:
        print(f"  [Discord] Error processing message: {e}")
        await send_response(message.channel, "❌ Error", f"Something went wrong: {str(e)[:100]}", color=discord.Color.red())
    finally:
        try:
            await message.remove_reaction("⏳", bot.user)
        except:
            pass

    await bot.process_commands(message)


def run_bot():
    if not DISCORD_BOT_TOKEN:
        print("  [Discord] No bot token found in .env")
        print("  [Discord] Set DISCORD_BOT_TOKEN in .env to enable Discord capture")
        return
    print("  [Discord] Starting Jarvis Discord bot...")
    bot.run(DISCORD_BOT_TOKEN)
