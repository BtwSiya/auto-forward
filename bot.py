import asyncio
import logging
import re
import random
import os
import sys
import time
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    MessageNotModified, ChatWriteForbidden, ChatAdminRequired,
    ChatForwardsRestricted, InviteHashExpired, UsernameNotOccupied
)
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, 
    InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
)

# ==========================================================
#                      CONFIGURATION
# ==========================================================

API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAG3Bk4L-xnpmu2IWMfRS_m5AG8foG7cPRc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

# Logging setup for debugging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("forwarder.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Clients
app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

# Global Storage
BATCH_TASKS = {}
USER_STATE = {}
PROCESSED_ALBUMS = []
LIVE_MONITORED_CHATS = []

# ==========================================================
#                     UTILITY FUNCTIONS
# ==========================================================

async def resolve_chat_id(link_or_id: str):
    """
    Powerful resolver that handles all types of Telegram links
    and automatically joins private chats if needed.
    """
    logger.info(f"Resolving: {link_or_id}")
    link_or_id = str(link_or_id).strip().rstrip("/")
    
    # 1. Check if it's a direct Numeric ID
    if re.match(r"^-?\d+$", link_or_id): 
        return int(link_or_id)
    
    # 2. Check for Private Link with /c/ format
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            chat_id = int("-100" + parts[parts.index('c') + 1])
            return chat_id
        except Exception as e:
            logger.error(f"Error resolving /c/ link: {e}")
            return None

    # 3. Check for Invite Links (+ or joinchat)
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            try:
                await userbot.join_chat(link_or_id)
                logger.info("Successfully joined the chat via invite link.")
            except UserAlreadyParticipant:
                logger.info("Userbot already a participant.")
            except Exception as e:
                logger.error(f"Join error: {e}")
            
            chat_info = await userbot.get_chat(link_or_id)
            return chat_info.id
        except Exception as e:
            logger.error(f"Invite resolution failed: {e}")
            return None

    # 4. Check for Public Usernames
    try:
        username = link_or_id.split('/')[-1]
        try:
            await userbot.join_chat(username)
        except:
            pass
        chat = await userbot.get_chat(username)
        return chat.id
    except Exception as e:
        logger.error(f"Public username resolution failed: {e}")
        return None

async def download_thumbnail(msg):
    """Downloads thumbnail to fix the black screen issue in restricted content."""
    try:
        if msg.video and msg.video.thumbs:
            return await userbot.download_media(msg.video.thumbs[0].file_id)
        if msg.document and msg.document.thumbs:
            return await userbot.download_media(msg.document.thumbs[0].file_id)
    except Exception as e:
        logger.debug(f"Thumbnail download skipped: {e}")
    return None

# ==========================================================
#                   SMART FORWARDING ENGINE
# ==========================================================

async def smart_forwarder(task_id, msg):
    """
    The brain of the forwarder. Handles albums, restricted content,
    text formatting, and cleanup.
    """
    t = BATCH_TASKS.get(task_id)
    if not t or not t['running']:
        return 0

    try:
        # --- Handle Albums (Media Groups) ---
        if msg.media_group_id:
            if msg.media_group_id in PROCESSED_ALBUMS:
                return 0 # Already handled by another instance
            
            # Mark as processed immediately
            PROCESSED_ALBUMS.append(msg.media_group_id)
            if len(PROCESSED_ALBUMS) > 1000: PROCESSED_ALBUMS.pop(0)

            try:
                # Try direct copy first
                await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                return 1 # We return 1 as a signal that the group was handled
            except ChatForwardsRestricted:
                # Fallback to Download and Upload
                album_msgs = await userbot.get_media_group(t['source'], msg.id)
                media_list = []
                files_to_delete = []
                
                for m in album_msgs:
                    file_path = await userbot.download_media(m)
                    files_to_delete.append(file_path)
                    thumb_path = await download_thumbnail(m)
                    if thumb_path: files_to_delete.append(thumb_path)
                    
                    caption = m.caption or ""
                    if m.photo:
                        media_list.append(InputMediaPhoto(file_path, caption=caption))
                    elif m.video:
                        media_list.append(InputMediaVideo(
                            file_path, caption=caption, thumb=thumb_path,
                            width=m.video.width, height=m.video.height,
                            duration=m.video.duration, supports_streaming=True
                        ))
                    elif m.document:
                        media_list.append(InputMediaDocument(file_path, caption=caption, thumb=thumb_path))
                    elif m.audio:
                        media_list.append(InputMediaAudio(file_path, caption=caption, thumb=thumb_path, duration=m.audio.duration))

                if media_list:
                    await userbot.send_media_group(t['dest'], media=media_list)
                
                # Cleanup
                for f in files_to_delete:
                    if f and os.path.exists(f): os.remove(f)
                return len(album_msgs)

        # --- Handle Single Messages ---
        else:
            if msg.text:
                # Direct message for text
                await userbot.send_message(t['dest'], msg.text, entities=msg.entities)
                return 1
            else:
                # Media or File
                try:
                    await userbot.copy_message(t['dest'], t['source'], msg.id)
                except ChatForwardsRestricted:
                    # Download bypass
                    f_path = await userbot.download_media(msg)
                    t_path = await download_thumbnail(msg)
                    cap = msg.caption or ""
                    
                    if msg.photo:
                        await userbot.send_photo(t['dest'], f_path, caption=cap)
                    elif msg.video:
                        await userbot.send_video(
                            t['dest'], f_path, caption=cap, thumb=t_path,
                            duration=msg.video.duration, width=msg.video.width,
                            height=msg.video.height, supports_streaming=True
                        )
                    elif msg.document:
                        await userbot.send_document(t['dest'], f_path, caption=cap, thumb=t_path)
                    elif msg.audio:
                        await userbot.send_audio(t['dest'], f_path, caption=cap, thumb=t_path, duration=msg.audio.duration)
                    elif msg.voice:
                        await userbot.send_voice(t['dest'], f_path, caption=cap)
                    
                    if f_path and os.path.exists(f_path): os.remove(f_path)
                    if t_path and os.path.exists(t_path): os.remove(t_path)
                return 1

    except Exception as e:
        logger.error(f"Smart Forwarder Error: {e}")
        t['last_error'] = str(e)[:100]
        return 0

# ==========================================================
#                   LIVE MONITORING HANDLER
# ==========================================================

@userbot.on_message(filters.group | filters.channel)
async def live_stream_monitor(client, message):
    """
    This handler listens for any new message in any chat the userbot is in.
    If the chat is a source for an active task, it forwards the message.
    """
    for task_id, task in BATCH_TASKS.items():
        if task['running'] and task['source'] == message.chat.id:
            # Check if we are already past this ID in the batch loop
            if message.id >= task['current']:
    # Instant Forwarding logic
            await userbot.copy_message(task['dest'], task['source'], message.id)
            task['total'] += 1
            task['current'] = message.id + 1
            await update_task_ui(task_id, "⚡ Live Forwarded!")
    
# ==========================================================
#                   CORE TASK MANAGEMENT
# ==========================================================

async def update_task_ui(task_id, activity_status):
    """Updates the bot's message with live statistics."""
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    status_icon = "🟢 Running" if t['running'] else "🛑 Stopped"
    report = (
        f"📊 **Live Task Report: {task_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Total Forwarded:** `{t['total']}`\n"
        f"📍 **Last Message ID:** `{t['current'] - 1}`\n"
        f"⚡ **Activity:** `{activity_status}`\n"
        f"📢 **Status:** {status_icon}\n"
        f"⚠️ **Last Error:** `{t['last_error']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 **Update Time:** `{time.strftime('%H:%M:%S')}`"
    )
    
    try:
        await app.edit_message_text(
            t['user_id'], t['log_msg_id'], report,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")
            ]])
        )
    except Exception:
        pass

async def task_worker_loop(task_id):
    """
    The background loop that handles 'Backlog' (old messages).
    Once finished, it keeps the task 'Running' for the Live Monitor.
    """
    t = BATCH_TASKS[task_id]
    logger.info(f"Worker started for Task {task_id}")
    
    try:
        # Step 1: Find the latest message ID in the source
        latest_history = []
        async for m in userbot.get_chat_history(t['source'], limit=1): latest_history.append(m)
        target_end_id = latest_history[0].id if latest_history else t['current']
        
        # Step 2: Process all old messages up to the current time
        while t['running'] and t['current'] <= target_end_id:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            if msg and not msg.empty and not msg.service:
                count = await smart_forwarder(task_id, msg)
                if count > 0:
                    t['total'] += count
                    await update_task_ui(task_id, "📥 Batching Backlog...")
            
            t['current'] += 1
            await asyncio.sleep(2) # Prevent FloodWait

        # Step 3: Switch to pure Live Monitoring mode
        if t['running']:
            await update_task_ui(task_id, "👀 Monitoring for New Messages...")
            
    except Exception as e:
        logger.error(f"Worker Loop Error for {task_id}: {e}")
        t['last_error'] = f"Loop: {str(e)[:50]}"

# ==========================================================
#                   BOT COMMANDS & UI
# ==========================================================

@app.on_message(filters.command("start") & filters.private)
async def start_command_handler(client, message):
    welcome_text = (
        "🚀 **Pro Forwarder Engine V10**\n\n"
        "This bot provides high-speed forwarding with real-time monitoring.\n\n"
        "**Core Capabilities:**\n"
        "• **Live Forwarding:** New posts arrive instantly.\n"
        "• **Restricted Content:** Bypass copy restrictions.\n"
        "• **Album Preservation:** Media groups stay together.\n"
        "• **Auto-Join:** Bot joins source/dest via link."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start New Task", callback_data="new_task")],
        [InlineKeyboardButton("📊 View Active Tasks", callback_data="view_tasks")]
    ])
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_callback_query()
async def callback_processor(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data
    
    if data == "new_task":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text(
            "🔗 **Step 1: Source Selection**\n\n"
            "Please send the **Source Chat Link**.\n"
            "Examples:\n"
            "• `https://t.me/example` (Public)\n"
            "• `https://t.me/c/12345/678` (Private Link)\n"
            "• `https://t.me/+AbCdEf` (Invite Link)"
        )
    
    elif data == "view_tasks":
        buttons = []
        for tid, t in BATCH_TASKS.items():
            if t['user_id'] == uid and t['running']:
                buttons.append([InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"kill_{tid}")])
        
        if not buttons:
            return await query.answer("You have no active tasks running.", show_alert=True)
        
        await query.message.edit_text("📋 **Currently Active Tasks:**", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ **Task {tid} has been terminated.**")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    
    current_step = USER_STATE[uid]["step"]
    
    if current_step == "SOURCE":
        wait_msg = await message.reply("🔍 **Validating Source...**")
        input_text = message.text.strip()
        
        start_id = 1
        # Extract ID if present in the link (e.g. t.me/chat/123)
        if "/" in input_text:
            last_part = input_text.split('/')[-1]
            if last_part.isdigit():
                start_id = int(last_part)
                input_text = input_text.rsplit('/', 1)[0]
        
        source_chat = await resolve_chat_id(input_text)
        if not source_chat:
            return await wait_msg.edit("❌ **Invalid Source!** Bot couldn't access this chat. Make sure the link is correct.")
        
        USER_STATE[uid].update({"source": source_chat, "start_id": start_id, "step": "DESTINATION"})
        await wait_msg.edit(
            f"✅ **Source Connected!** (Chat ID: `{source_chat}`)\n"
            f"📍 **Starting from ID:** `{start_id}`\n\n"
            "📥 **Step 2: Destination Selection**\n"
            "Please send the **Destination Chat Link** where messages should be sent."
        )

    elif current_step == "DESTINATION":
        wait_msg = await message.reply("🔍 **Validating Destination...**")
        dest_chat = await resolve_chat_id(message.text)
        
        if not dest_chat:
            return await wait_msg.edit("❌ **Invalid Destination!** Bot couldn't access the target chat.")
        
        # All data collected, start the task
        task_id = random.randint(100000, 999999)
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'],
            "dest": dest_chat,
            "current": USER_STATE[uid]['start_id'],
            "total": 0,
            "running": True,
            "user_id": uid,
            "log_msg_id": wait_msg.id,
            "last_error": "None"
        }
        
        del USER_STATE[uid]
        await wait_msg.edit(f"🚀 **Task {task_id} Initialized!**\nBatching old messages & Monitoring live ones...")
        
        # Start the background worker
        asyncio.create_task(task_worker_loop(task_id))

# ==========================================================
#                      MAIN EXECUTION
# ==========================================================

async def run_bot():
    print("Starting Bot...")
    await app.start()
    print("Starting Userbot...")
    await userbot.start()
    print("Both clients are online. System Ready.")
    await idle()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(run_bot())
    except KeyboardInterrupt:
        print("Bot Stopped.")
                
