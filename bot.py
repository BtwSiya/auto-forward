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

# ================= SMART UTILS =================

async def resolve_chat(link_or_id: str):
    """Smartly resolves chat ID and joins if necessary."""
    link_or_id = str(link_or_id).strip()
    
    # 1. Direct Numeric ID
    if re.match(r"^-?\d+$", link_or_id):
        return int(link_or_id)
    
    # 2. Private Channel Link (t.me/c/1234/5)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None

    # 3. Public/Private Invite Links
    try:
        if "t.me/+" in link_or_id or "t.me/joinchat/" in link_or_id:
            try:
                chat = await userbot.join_chat(link_or_id)
                return chat.id
            except UserAlreadyParticipant:
                # If already joined, get chat info to get ID
                chat = await userbot.get_chat(link_or_id)
                return chat.id
        else:
            # Public Username or Link
            username = link_or_id.split('/')[-1]
            try:
                await userbot.join_chat(username)
            except: pass
            chat = await userbot.get_chat(username)
            return chat.id
    except Exception as e:
        logger.error(f"Resolve Error: {e}")
        return None

# ================= CORE ENGINE =================

async def update_live_report(task_id):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    status = "🟢 Running" if t['running'] else "🛑 Stopped"
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n\n"
        f"📢 **Status:** {status}\n"
        f"⚠️ **Last Error:** `{t['last_error']}`"
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
                    # 1. Try Direct Copy
                    await userbot.copy_message(t['dest'], t['source'], msg.id)
                    t['total'] += 1
                except ChatForwardsRestricted:
                    # 2. Bypass Protected Content (Download & Upload)
                    try:
                        path = await userbot.download_media(msg)
                        if path:
                            if msg.photo: await userbot.send_photo(t['dest'], path, caption=msg.caption)
                            elif msg.video: await userbot.send_video(t['dest'], path, caption=msg.caption)
                            else: await userbot.send_document(t['dest'], path, caption=msg.caption)
                            os.remove(path)
                            t['total'] += 1
                        else: raise Exception("Download Fail")
                    except Exception as e:
                        t['failed'] += 1
                        t['last_error'] = f"Bypass Fail: {str(e)}"
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e) # Error limit removed to show full error

            t['current'] += 1
            # Update live report
            await update_live_report(task_id)
            await asyncio.sleep(3) # 3s delay

        except FloodWait as e:
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Loop Error: {str(e)}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Advanced Media Forwarder v5**\n\n"
        "**Features:**\n"
        "✅ Bypass Protected Content\n"
        "✅ Auto-Join Channels\n"
        "✅ Live Progress Tracking"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start Forwarding", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Active Tasks", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data

    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:**\nSend the **Source Channel Link**.")

    elif data == "view_status":
        active_btns = []
        for tid, t_info in BATCH_TASKS.items():
            if t_info['running'] and t_info['user_id'] == uid:
                active_btns.append([InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"kill_{tid}")])
        if not active_btns: return await query.answer("No active tasks!", show_alert=True)
        await query.message.edit_text("📋 **Active Monitor:**", reply_markup=InlineKeyboardMarkup(active_btns))

    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ **Task {tid} Stopped.**")
            del BATCH_TASKS[tid]

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return

    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        msg = await message.reply("🔍 Checking Source...")
        source = await resolve_chat(message.text)
        if not source: return await msg.edit("❌ **Invalid Source!** Bot/Userbot cannot join.")
        
        start_id = 1
        if "/" in message.text and message.text.split("/")[-1].isdigit():
            start_id = int(message.text.split("/")[-1])
            
        USER_STATE[uid] = {"step": "DEST", "source": source, "start": start_id}
        await msg.edit(f"✅ **Source Found!** Starting from ID: `{start_id}`\n\n📥 **Step 2:**\nSend **Destination Channel Link**.")

    elif step == "DEST":
        msg = await message.reply("🔍 Checking Destination...")
        dest = await resolve_chat(message.text)
        if not dest: return await msg.edit("❌ **Invalid Destination!** Check permissions.")
        
        task_data = USER_STATE[uid]
        task_id = random.randint(1000, 9999)
        
        BATCH_TASKS[task_id] = {
            "source": task_data['source'], "dest": dest, "current": task_data['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        
        del USER_STATE[uid]
        await msg.edit(f"🚀 **Task {task_id} Initialized!**\n\n*Forwarding will start in 3s...*")
        asyncio.create_task(run_batch_worker(task_id))

# ================= BOOT =================

async def main():
    await app.start()
    await userbot.start()
    print("--- Pro Forwarder V5 Ready ---")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
        
