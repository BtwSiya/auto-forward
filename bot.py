import asyncio
import logging
import re
import random
import os
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

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    link_or_id = str(link_or_id).strip()
    try:
        if re.match(r"^-?\d+$", link_or_id): return int(link_or_id)
        if "t.me/c/" in link_or_id:
            return int("-100" + link_or_id.split("t.me/c/")[1].split("/")[0])
        
        try:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        except UserAlreadyParticipant:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
        except Exception:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
    except Exception: return None

# ================= CORE ENGINE =================

async def update_live_report(task_id):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    status = "⚙️ Processing" if t['running'] else "🛑 Stopped"
    
    # UI Updated to show full error
    text = (
        f"📊 **Live Task Report: {task_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 **Status:** {status}\n"
        f"⚠️ **Last Error:**\n`{t['last_error']}`"
    )
    
    try:
        await app.edit_message_text(
            t['user_id'], t['log_msg_id'], text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except Exception: pass

async def run_batch_worker(task_id):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            if not msg or msg.empty:
                t['skipped'] += 1
                t['current'] += 1
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(t['dest'], t['source'], msg.id)
                    t['total'] += 1
                except ChatForwardsRestricted:
                    try:
                        file_path = await userbot.download_media(msg)
                        if file_path:
                            if msg.photo: await userbot.send_photo(t['dest'], file_path, caption=msg.caption)
                            elif msg.video: await userbot.send_video(t['dest'], file_path, caption=msg.caption)
                            elif msg.document: await userbot.send_document(t['dest'], file_path, caption=msg.caption)
                            os.remove(file_path)
                            t['total'] += 1
                        else: raise Exception("Download Failed")
                    except Exception as e:
                        t['failed'] += 1
                        t['last_error'] = f"Download/Upload: {str(e)}"
                except ChatAdminRequired:
                    t['last_error'] = "400 CHAT_ADMIN_REQUIRED: Bot needs admin in destination."
                    t['failed'] += 1
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e) # Removed the [:30] limit to show full error

            t['current'] += 1
            # Update more frequently for live feel
            await update_live_report(task_id)
            await asyncio.sleep(3)

        except FloodWait as e:
            t['last_error'] = f"FloodWait: Sleeping for {e.value}s"
            await update_live_report(task_id)
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Engine Error: {str(e)}"
            await update_live_report(task_id)
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "👋 **Welcome to Media Forwarder V4**\n\n"
        "I can bypass **Protected Content** restrictions.\n"
        "Please ensure the Userbot is admin in Destination."
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start New Batch", callback_data="setup_src")],
        [InlineKeyboardButton("📊 My Tasks", callback_data="status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_manager(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data

    if data == "setup_src":
        USER_STATE[uid] = {"step": "SRC"}
        await query.message.edit_text("🔗 **Step 1/3:**\nSend the **Source** Channel Link or ID.")

    elif data == "status":
        active_btns = []
        for tid, t_info in BATCH_TASKS.items():
            if t_info['running'] and t_info['user_id'] == uid:
                active_btns.append([InlineKeyboardButton(f"📊 Monitor Task {tid}", callback_data=f"mon_{tid}")])
        if not active_btns: return await query.answer("No active tasks.", show_alert=True)
        await query.message.edit_text("📋 **Active Tasks Monitor:**", reply_markup=InlineKeyboardMarkup(active_btns))

    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ Task `{tid}` has been stopped.")
            del BATCH_TASKS[tid]

@app.on_message(filters.private & ~filters.command("start"))
async def setup_flow(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    
    state = USER_STATE[uid]
    
    if state['step'] == "SRC":
        chat = await resolve_chat(message.text)
        if not chat: return await message.reply("❌ Invalid Source/Userbot not joined.")
        
        start_id = 1
        if "/" in message.text and message.text.split("/")[-1].isdigit():
            start_id = int(message.text.split("/")[-1])
            
        USER_STATE[uid].update({"src": chat, "start": start_id, "step": "DEST"})
        await message.reply(f"✅ Source Set. Start ID: `{start_id}`\n\n📥 **Step 2/3:**\nSend **Destination** Channel Link/ID.")

    elif state['step'] == "DEST":
        chat = await resolve_chat(message.text)
        if not chat: return await message.reply("❌ Invalid Destination.")
        
        USER_STATE[uid].update({"dest": chat})
        tid = random.randint(1000, 9999)
        
        log_msg = await message.reply(f"⏳ **Initializing Task {tid}...**")
        
        BATCH_TASKS[tid] = {
            "source": state['src'], "dest": chat, "current": state['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": log_msg.id, "last_error": "None"
        }
        
        del USER_STATE[uid]
        asyncio.create_task(run_batch_worker(tid))

# ================= BOOT =================

async def main():
    await app.start()
    await userbot.start()
    print("V4 PROTECTED FORWARDER READY")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    
