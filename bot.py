import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

# ================= CONFIGURATION =================
# Replace these with your actual details or keep importing from config
try:
    from config import API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, OWNER_ID
except ImportError:
    # Fill these if you don't have a config.py
    API_ID = 21705136
    API_HASH = "78730e89d196e160b0f1992018c6cb19"
    BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
    SESSION_STRING = "" # Userbot session is MUST for private channels
    OWNER_ID = [123456789] 

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Clients
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Userbot is required to see messages in channels and copy them
userbot = Client(
    "my_userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= GLOBAL STORAGE =================
# Format: { source_chat_id: { 'dest_id': destination_chat_id, 'user_id': owner_id } }
WATCH_LIST = {}

# ================= HELPER FUNCTIONS =================

async def get_chat_id(client, link: str):
    """Extracts Chat ID from a link or username."""
    if "t.me/" in link:
        if "/+" in link or "joinchat" in link:
            try:
                chat = await client.join_chat(link)
                return chat.id
            except Exception as e:
                logger.error(f"Error joining chat: {e}")
                return None
        
        # Handle t.me/c/123456789/10 format (Private links)
        if "t.me/c/" in link:
            parts = link.split("/")
            # Pyrogram needs -100 prefix for private channel IDs derived from links
            return int("-100" + parts[4])
        
        # Handle t.me/username format
        username = link.split("/")[-1]
        try:
            chat = await client.get_chat(username)
            return chat.id
        except Exception:
            return None
    
    # If user sent an ID directly (e.g., -100123456)
    try:
        return int(link)
    except ValueError:
        return None

# ================= BOT COMMANDS =================

@app.on_message(filters.command("start") & filters.private)
async def start_command(_, message):
    await message.reply(
        "👋 **Welcome to the Auto-Forward Bot!**\n\n"
        "Use `/batch` to start connecting a source channel to a destination channel.\n"
        "Once connected, any **new** post in the source will be sent to your destination."
    )

@app.on_message(filters.command("batch") & filters.private)
async def start_batch(client, message):
    user_id = message.chat.id
    
    # 1. Ask for Source Channel
    try:
        source_msg = await client.ask(
            user_id, 
            "**📥 Send the Source Channel Link or ID.**\n"
            "(The channel where messages come FROM. Make sure the Userbot has joined it.)"
        )
    except Exception:
        return
    
    if source_msg.text == "/cancel":
        return await message.reply("Cancelled.")

    source_id = await get_chat_id(userbot, source_msg.text)
    
    if not source_id:
        return await message.reply("❌ Could not get Channel ID. Make sure the Userbot is part of that chat or the link is valid.")

    # 2. Ask for Destination Channel
    try:
        dest_msg = await client.ask(
            user_id, 
            "**📤 Send the Destination Channel ID.**\n"
            "(The channel where messages should go. Make sure the Bot is Admin there.)"
        )
    except Exception:
        return

    if dest_msg.text == "/cancel":
        return await message.reply("Cancelled.")

    try:
        dest_id = int(dest_msg.text)
    except ValueError:
        return await message.reply("❌ Invalid Destination ID. Please send the numeric ID (e.g., -10012345...).")

    # 3. Save to Watch List
    WATCH_LIST[source_id] = {'dest_id': dest_id, 'user_id': user_id}
    
    await message.reply(
        f"✅ **Auto-Forwarding Started!**\n\n"
        f"**Source:** `{source_id}`\n"
        f"**Destination:** `{dest_id}`\n\n"
        f"🚀 Any **NEW** message sent to the source will now be copied to the destination.\n"
        f"Use `/stop` to stop watching."
    )
    print(f"Started watching: {source_id} -> {dest_id}")


@app.on_message(filters.command("stop") & filters.private)
async def stop_batch(_, message):
    # This is a simple stop command. For a multi-user bot, you'd filter by user_id.
    # Here we clear all for the user or just clear the dict.
    global WATCH_LIST
    if not WATCH_LIST:
        await message.reply("Nothing is currently running.")
        return
        
    WATCH_LIST.clear()
    await message.reply("🛑 All auto-forwarding tasks have been stopped.")


@app.on_message(filters.command("status") & filters.private)
async def status_batch(_, message):
    if not WATCH_LIST:
        await message.reply("💤 No active forwarders running.")
    else:
        text = "**Active Connections:**\n\n"
        for src, data in WATCH_LIST.items():
            text += f"🔹 Source: `{src}` ➡ Dest: `{data['dest_id']}`\n"
        await message.reply(text)


# ================= THE ENGINE (LISTENER) =================

@userbot.on_message(filters.incoming)
async def auto_forward_engine(client, message: Message):
    """
    This function listens to every message the Userbot receives.
    If the message comes from a Source Channel in WATCH_LIST, it forwards it.
    """
    if not message.chat:
        return

    source_id = message.chat.id

    # Check if this chat is in our watch list
    if source_id in WATCH_LIST:
        target_data = WATCH_LIST[source_id]
        dest_id = target_data['dest_id']
        
        try:
            # COPY the message to the destination (Preserves media, captions, etc.)
            # We use 'app' (The Bot) to send to destination if possible, 
            # otherwise 'userbot' if the bot isn't in the destination.
            # Usually, Bot is admin in destination.
            
            # Method 1: Try copying via Bot (Cleaner, acts as bot)
            try:
                await app.copy_message(
                    chat_id=dest_id,
                    from_chat_id=source_id,
                    message_id=message.id
                )
            except Exception:
                # Method 2: Fallback to Userbot (If bot fails or can't see source msg details)
                await client.copy_message(
                    chat_id=dest_id,
                    from_chat_id=source_id,
                    message_id=message.id
                )
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            # Retry once after sleep
            await client.copy_message(chat_id=dest_id, from_chat_id=source_id, message_id=message.id)
        except Exception as e:
            print(f"Error forwarding message: {e}")

# ================= MAIN EXECUTION =================

async def main():
    print("Starting Bot and Userbot...")
    await app.start()
    await userbot.start()
    print("Bot is ready! Send /batch to start.")
    await idle()
    await app.stop()
    await userbot.stop()

if __name__ == "__main__":
    # Needed for Pyrogram 2.0+
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

