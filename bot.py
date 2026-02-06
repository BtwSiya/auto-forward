import asyncio
import logging
import re
import random
import os
import time
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    MessageNotModified, ChatWriteForbidden, ChatAdminRequired,
    ChatForwardsRestricted
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAErREWZ0rxRYnzyJw06dRgOsrwQRcEhlkc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

BATCH_TASKS = {}
USER_STATE = {}

# ================= SMART UTILS =================

async def resolve_chat(link_or_id: str):
    link_or_id = str(link_or_id).strip()
    if re.match(r"^-?\d+$", link_or_id): return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None
    try:
        if "t.me/+" in link_or_id or "t.me/joinchat/" in link_or_id:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        else:
            username = link_or_id.split('/')[-1]
            try: await userbot.join_chat(username)
            except: pass
            chat = await userbot.get_chat(username)
            return chat.id
    except Exception: return None

# ================= CORE ENGINE =================

async def update_live_report(task_id, current_status="Running"):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n\n"
        f"⚡ **Activity:** `{current_status}`\n"
        f"📢 **Status:** {'🟢 Running' if t['running'] else '🛑 Stopped'}\n"
        f"⚠️ **Last Error:** `{t['last_error']}`"
    )
    
    try:
        await app.edit_message_text(
            t['user_id'], t['log_msg_id'], text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except: pass

async def progress(current, total, task_id, mode):
    # Update status every 10% to avoid flood
    percentage = current * 100 / total
    if int(percentage) % 20 == 0:
        await update_live_report(task_id, f"{mode}: {percentage:.1f}%")

async def run_batch_worker(task_id):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            if not msg or msg.empty:
                t['skipped'] += 1
                t['current'] += 1
                continue

            try:
                # 1. Handle Albums (Grouping)
                if msg.media_group_id:
                    await update_live_report(task_id, "Processing Album...")
                    try:
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += 1
                        # Increment current by group size approximately (or handle properly)
                        t['current'] += 1 
                    except ChatForwardsRestricted:
                        # For restricted albums, we process each message in the group
                        album = await userbot.get_media_group(t['source'], msg.id)
                        for m in album:
                            path = await userbot.download_media(m, progress=progress, progress_args=(task_id, "Downloading"))
                            await userbot.send_document(t['dest'], path, caption=m.caption, progress=progress, progress_args=(task_id, "Uploading"))
                            if os.path.exists(path): os.remove(path)
                        t['total'] += 1
                
                # 2. Handle Single Messages
                else:
                    try:
                        await userbot.copy_message(t['dest'], t['source'], msg.id)
                        t['total'] += 1
                    except ChatForwardsRestricted:
                        await update_live_report(task_id, "Bypassing Restriction...")
                        path = await userbot.download_media(msg, progress=progress, progress_args=(task_id, "Downloading"))
                        if path:
                            await update_live_report(task_id, "Uploading File...")
                            if msg.photo: await userbot.send_photo(t['dest'], path, caption=msg.caption)
                            elif msg.video: await userbot.send_video(t['dest'], path, caption=msg.caption)
                            else: await userbot.send_document(t['dest'], path, caption=msg.caption)
                            if os.path.exists(path): os.remove(path)
                            t['total'] += 1

            except Exception as e:
                t['failed'] += 1
                t['last_error'] = str(e)[:50]

            t['current'] += 1
            await update_live_report(task_id, "Waiting for next...")
            await asyncio.sleep(3)

        except FloodWait as e:
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Loop: {str(e)[:50]}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = "🚀 **Advanced Media Forwarder v5**\n✅ Unlimited Size Support\n✅ Album Grouping Fix"
    btns = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Start Forwarding", callback_data="new_batch")]])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid, data = query.from_user.id, query.data
    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:** Send Source Channel Link.")
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"🛑 Task {tid} Stopped.")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        source = await resolve_chat(message.text)
        if not source: return await message.reply("❌ Invalid Source!")
        start_id = int(message.text.split('/')[-1]) if message.text.split('/')[-1].isdigit() else 1
        USER_STATE[uid].update({"step": "DEST", "source": source, "start": start_id})
        await message.reply("📥 **Step 2:** Send Destination Channel Link.")
    elif step == "DEST":
        dest = await resolve_chat(message.text)
        if not dest: return await message.reply("❌ Invalid Destination!")
        task_id = random.randint(1000, 9999)
        msg = await message.reply("🚀 Initializing Task...")
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": dest, "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        del USER_STATE[uid]
        asyncio.create_task(run_batch_worker(task_id))

async def main():
    await app.start()
    await userbot.start()
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
                                                              
