import asyncio
import logging
import random
import re
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8573758498:AAEplnYzHwUmjYRFiRSdCAFwyPfYIjk7RIk"
SESSION_STRING = "BQFLMbAAb_m5J6AV43eGHnXxxkz8mVJFBOTLcZay_IX7YtklY4S9Z6E0XjPUUoIoM33-BocBlogwRsQsdA8u9YeuLMu1Cmuws3OZISIv3xLz_vAJJAk6mmqeflAkh5X35T6QP-SnbSnd-9FD-fWdP7GyKoJMIrV37RbPym31xaSdOOJjzlf781CIwcoxvTnjqcWzyWlhQS0I7o7nVbmDDCR7rBTlmkMHiN1IjFpxg2Itcc5XjdbG-2JlCOuomw7iWwk3WF-tTbHXCBXNgFEXBzx7mnrY9jr9sCtnx4UHsqq4NiofutkrcX0aZ-TYTwf5RhfGonZjBaHaNZ-lkrREC4YHfqLoWQAAAAGd7PcCAA"

# Optimized logging
logging.basicConfig(level=logging.ERROR)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global Storage
BATCH_TASKS = {}
USER_STATE = {} # Tracking {user_id: {"step": "SOURCE/DEST", "data": {}}}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    """Resolves any link/ID to a Chat ID and joins if needed."""
    link_or_id = link_or_id.strip()
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

# ================= CORE ENGINE =================

async def run_batch_worker(task_id):
    """The 24/7 worker with a 2-second pulse."""
    task = BATCH_TASKS[task_id]
    print(f"DEBUG: Worker started for Task {task_id}")

    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            # Fetch message using userbot (bypasses restrictions)
            msg = await userbot.get_messages(task['source'], task['current'])
            
            if not msg or msg.empty:
                # No message found? Wait 2 seconds for new posts
                await asyncio.sleep(2)
                continue

            if not msg.service:
                try:
                    # Restricted content is handled natively by .copy_message
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    await asyncio.sleep(2) # Mandatory anti-flood delay
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                except Exception:
                    pass # Skip deleted/inaccessible messages

            task['current'] += 1

        except Exception as e:
            await asyncio.sleep(5) # Cooldown on global error

@userbot.on_message(filters.incoming)
async def instant_forwarder(client, message):
    """Handles real-time forwarding for messages arriving during a batch."""
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            if message.id >= task['current']:
                try:
                    await userbot.copy_message(task['dest'], task['source'], message.id)
                except: pass

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    USER_STATE[message.from_user.id] = None # Reset state on start
    welcome_text = (
        f"✨ **Premium Forwarder Service** ✨\n\n"
        f"Hello {message.from_user.first_name}! I am optimized for 24/7 "
        f"background forwarding with Restricted Content support.\n\n"
        f"🚀 **Pulse Interval:** `2 Seconds`"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start New Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Active Status", callback_data="view_status")]
    ])
    await message.reply(welcome_text, reply_markup=buttons)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid = query.from_user.id

    if query.data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text(
            "🔗 **Step 1:**\nPlease send the **Source Link or ID**.\n\n"
            "Example: `https://t.me/c/12345/100`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="back_home")]])
        )

    elif query.data == "view_status":
        my_tasks = {k: v for k, v in BATCH_TASKS.items() if v['user_id'] == uid and v['running']}
        if not my_tasks:
            return await query.answer("No active batches found!", show_alert=True)
        
        status_text = "📊 **Active Processing Tasks:**\n\n"
        btns = []
        for tid, data in my_tasks.items():
            status_text += f"🔹 **Task:** `{tid}` | **Msg ID:** `{data['current']}`\n"
            btns.append([InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"stop_{tid}")])
        
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text(status_text, reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Task {tid} has been stopped.", show_alert=True)
            await query.message.delete()

    elif query.data == "back_home":
        await start_handler(client, query.message)

@app.on_message(filters.private & ~filters.command("start"))
async def state_processor(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE or not USER_STATE[uid]:
        return

    step = USER_STATE[uid]["step"]

    if step == "SOURCE":
        source_id = await resolve_chat(message.text)
        msg_id = extract_msg_id(message.text)
        
        if not source_id:
            return await message.reply("❌ **Invalid Source!** Please send a valid link or numeric ID.")
        
        USER_STATE[uid] = {"step": "DEST", "source": source_id, "start_id": msg_id}
        await message.reply("📥 **Step 2:**\nNow send the **Destination Link or ID**.")

    elif step == "DEST":
        dest_id = await resolve_chat(message.text)
        if not dest_id:
            return await message.reply("❌ **Invalid Destination!** Ensure the Userbot is a member of that chat.")

        task_data = USER_STATE[uid]
        task_id = random.randint(100, 999)
        
        BATCH_TASKS[task_id] = {
            "source": task_data['source'],
            "dest": dest_id,
            "current": task_data['start_id'],
            "running": True,
            "user_id": uid
        }

        USER_STATE[uid] = None # Clear state
        asyncio.create_task(run_batch_worker(task_id))
        
        await message.reply(
            f"✅ **Batch {task_id} Started!**\n\n"
            f"🚀 The bot will now forward messages every 2 seconds. "
            f"Restricted content is supported automatically."
        )

# ================= BOOT =================

async def main():
    await app.start()
    await userbot.start()
    print("--- 🟢 Forwarder is Online & Stable ---")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
                                               
