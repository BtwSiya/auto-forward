import asyncio
import logging
import random
import re
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant, MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAErREWZ0rxRYnzyJw06dRgOsrwQRcEhlkc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.ERROR)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global Storage
BATCH_TASKS = {} # {task_id: {data}}
USER_STATE = {}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    link_or_id = str(link_or_id).strip()
    if re.match(r"^-?\d+$", link_or_id):
        return int(link_or_id)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None
    if any(x in link_or_id for x in ["t.me/+", "t.me/joinchat/"]):
        try:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        except UserAlreadyParticipant:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
        except: return None
    if "t.me/" in link_or_id:
        username = link_or_id.split('/')[-1]
        try:
            chat = await userbot.get_chat(username)
            return chat.id
        except: return None
    return None

def extract_msg_id(link: str):
    try: return int(link.split("/")[-1])
    except: return 1

# ================= LIVE MONITOR ENGINE =================

async def update_log(task_id):
    """Updates the progress message in DM every few seconds."""
    task = BATCH_TASKS.get(task_id)
    if not task: return
    
    try:
        log_text = (
            f"📊 **Live Task Report: {task_id}**\n\n"
            f"📤 **Source:** `{task['source']}`\n"
            f"📥 **Destination:** `{task['dest']}`\n"
            f"🔄 **Current Msg ID:** `{task['current']}`\n"
            f"✅ **Total Forwarded:** `{task['total']}`\n\n"
            f"⏳ *Status: Running...*"
        )
        await app.edit_message_text(
            task['user_id'], 
            task['log_msg_id'], 
            log_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except MessageNotModified: pass
    except Exception: pass

async def run_batch_worker(task_id):
    """The Engine: Handles backlog and real-time syncing."""
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        task = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(task['source'], task['current'])
            
            if not msg or msg.empty:
                await asyncio.sleep(5) # Auto-check interval
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    task['total'] += 1
                    # Update Log Message in DM
                    if task['total'] % 2 == 0: # Update every 2 messages to save API hits
                        await update_log(task_id)
                    await asyncio.sleep(3) # 3s delay as requested
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                except Exception: pass

            task['current'] += 1
            
        except Exception:
            await asyncio.sleep(5)

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    USER_STATE[message.from_user.id] = None
    text = (
        "🚀 **Advanced Media Forwarder v3**\n\n"
        "**System:** `Stable & Monitoring ✅`\n"
        "**Features:** `Live Logs`, `3s Delay`, `Auto-Sync`"
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
        await query.message.edit_text("🔗 **Step 1:**\nSend the **Source Channel Link/ID**.")

    elif data == "view_status":
        active_btns = []
        for tid, t_info in BATCH_TASKS.items():
            if t_info['running'] and t_info['user_id'] == uid:
                active_btns.append([InlineKeyboardButton(f"🛑 Kill Task {tid} (Msg: {t_info['current']})", callback_data=f"kill_{tid}")])
        
        if not active_btns:
            return await query.answer("No active tasks found!", show_alert=True)
        
        active_btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text("📋 **System Monitor:**\nSelect a task to terminate it.", reply_markup=InlineKeyboardMarkup(active_btns))

    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Task {tid} Stopped!", show_alert=True)
            await query.message.edit_text(f"✅ **Task {tid} has been terminated.**")
            del BATCH_TASKS[tid]

    elif data == "back_home":
        await start_handler(client, query.message)

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE or not USER_STATE[uid]: return

    step = USER_STATE[uid]["step"]
    if step == "SOURCE":
        source = await resolve_chat(message.text)
        start_id = extract_msg_id(message.text)
        if not source: return await message.reply("❌ **Invalid Source!** Check Userbot.")
        USER_STATE[uid] = {"step": "DEST", "source": source, "current": start_id}
        await message.reply("📥 **Step 2:**\nSend the **Destination Channel ID or Link**.")

    elif step == "DEST":
        dest = await resolve_chat(message.text)
        if not dest: return await message.reply("❌ **Invalid Destination!** Check Bot Permissions.")
        
        task_data = USER_STATE[uid]
        task_id = random.randint(100, 999)
        
        # Create a Log Message that will be edited later
        log_msg = await message.reply(f"⏳ **Initializing Task {task_id}...**")
        
        BATCH_TASKS[task_id] = {
            "source": task_data['source'],
            "dest": dest,
            "current": task_data['current'],
            "total": 0,
            "running": True,
            "user_id": uid,
            "log_msg_id": log_msg.id
        }
        
        USER_STATE[uid] = None
        asyncio.create_task(run_batch_worker(task_id))

# ================= BOOT =================

async def main():
    await app.start()
    await userbot.start()
    print("--- Pro Forwarder Ready ---")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
