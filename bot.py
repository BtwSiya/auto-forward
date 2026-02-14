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

# Logging setup
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

# ==========================================================
#                     UTILITY FUNCTIONS
# ==========================================================

async def resolve_chat_id(link_or_id: str):
    link_or_id = str(link_or_id).strip().rstrip("/")
    if re.match(r"^-?\d+$", link_or_id): 
        return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None
    if "+" in link_or_id or "joinchat" in link_or_id:
        try:
            await userbot.join_chat(link_or_id)
            chat_info = await userbot.get_chat(link_or_id)
            return chat_info.id
        except: return None
    try:
        username = link_or_id.split('/')[-1]
        chat = await userbot.get_chat(username)
        return chat.id
    except: return None

async def download_thumbnail(msg):
    try:
        if msg.video and msg.video.thumbs:
            return await userbot.download_media(msg.video.thumbs[0].file_id)
        if msg.document and msg.document.thumbs:
            return await userbot.download_media(msg.document.thumbs[0].file_id)
    except: pass
    return None

# ==========================================================
#                   SMART FORWARDING ENGINE
# ==========================================================

async def smart_forwarder(task_id, msg):
    t = BATCH_TASKS.get(task_id)
    if not t or not t['running']: return 0
    try:
        if msg.media_group_id:
            if msg.media_group_id in PROCESSED_ALBUMS: return 0
            PROCESSED_ALBUMS.append(msg.media_group_id)
            if len(PROCESSED_ALBUMS) > 1000: PROCESSED_ALBUMS.pop(0)
            try:
                await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                return 1
            except ChatForwardsRestricted:
                album_msgs = await userbot.get_media_group(t['source'], msg.id)
                media_list = []
                files = []
                for m in album_msgs:
                    f_path = await userbot.download_media(m)
                    files.append(f_path)
                    cap = m.caption or ""
                    if m.photo: media_list.append(InputMediaPhoto(f_path, caption=cap))
                    elif m.video: media_list.append(InputMediaVideo(f_path, caption=cap))
                    elif m.document: media_list.append(InputMediaDocument(f_path, caption=cap))
                if media_list: await userbot.send_media_group(t['dest'], media=media_list)
                for f in files: 
                    if f and os.path.exists(f): os.remove(f)
                return len(album_msgs)
        else:
            try:
                await userbot.copy_message(t['dest'], t['source'], msg.id)
            except ChatForwardsRestricted:
                f_path = await userbot.download_media(msg)
                cap = msg.caption or ""
                if msg.photo: await userbot.send_photo(t['dest'], f_path, caption=cap)
                elif msg.video: await userbot.send_video(t['dest'], f_path, caption=cap)
                elif msg.document: await userbot.send_document(t['dest'], f_path, caption=cap)
                elif msg.text: await userbot.send_message(t['dest'], msg.text)
                if f_path and os.path.exists(f_path): os.remove(f_path)
            return 1
    except Exception as e:
        t['last_error'] = str(e)[:50]
        return 0

# ==========================================================
#                   LIVE MONITORING HANDLER
# ==========================================================

@userbot.on_message(filters.group | filters.channel)
async def live_stream_monitor(client, message):
    for task_id, task in BATCH_TASKS.items():
        if task['running'] and task['source'] == message.chat.id:
            if message.id >= task['current']:
                success_count = await smart_forwarder(task_id, message)
                if success_count > 0:
                    task['total'] += success_count
                    task['current'] = message.id + 1
                    await update_task_ui(task_id, "⚡ Live Message Forwarded!")

# ==========================================================
#                   CORE TASK MANAGEMENT
# ==========================================================

async def update_task_ui(task_id, activity_status):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    status_icon = "🟢 Running" if t['running'] else "🛑 Stopped"
    report = (
        f"📊 **Live Task Report: {task_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Total Forwarded:** `{t['total']}`\n"
        f"📍 **Last ID:** `{t['current'] - 1}`\n"
        f"⚡ **Activity:** `{activity_status}`\n"
        f"📢 **Status:** {status_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        await app.edit_message_text(t['user_id'], t['log_msg_id'], report,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task", callback_data=f"kill_{task_id}")]]))
    except: pass

async def task_worker_loop(task_id):
    t = BATCH_TASKS[task_id]
    try:
        latest = await userbot.get_chat_history(t['source'], limit=1)
        async for msg in userbot.get_chat_history(t['source'], offset_id=t['current'], reverse=True):
            if not t['running']: break
            count = await smart_forwarder(task_id, msg)
            if count > 0:
                t['total'] += count
                t['current'] = msg.id
                await update_task_ui(task_id, "📥 Batching Backlog...")
            await asyncio.sleep(1)
        await update_task_ui(task_id, "👀 Monitoring Live...")
    except Exception as e:
        t['last_error'] = str(e)[:50]

# ==========================================================
#                   BOT COMMANDS & UI
# ==========================================================

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ New Task", callback_data="new_task")]])
    await message.reply_text("🚀 **Pro Forwarder V10**\nClick below to start.", reply_markup=kb)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    if query.data == "new_task":
        USER_STATE[query.from_user.id] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 Send the **Source Chat Link**:")
    elif query.data.startswith("kill_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS: BATCH_TASKS[tid]['running'] = False
        await query.message.edit_text("✅ Task Stopped.")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    
    step = USER_STATE[uid]["step"]
    if step == "SOURCE":
        res = await resolve_chat_id(message.text)
        if res:
            USER_STATE[uid].update({"source": res, "step": "DESTINATION"})
            await message.reply("✅ Source Set! Now send **Destination Link**:")
        else: await message.reply("❌ Invalid Link.")
    elif step == "DESTINATION":
        res = await resolve_chat_id(message.text)
        if res:
            tid = random.randint(1000, 9999)
            wait = await message.reply("🚀 Starting...")
            BATCH_TASKS[tid] = {"source": USER_STATE[uid]['source'], "dest": res, "current": 1, "total": 0, "running": True, "user_id": uid, "log_msg_id": wait.id, "last_error": ""}
            del USER_STATE[uid]
            asyncio.create_task(task_worker_loop(tid))
        else: await message.reply("❌ Invalid Link.")

async def main():
    await app.start()
    await userbot.start()
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    
