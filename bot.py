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

# Minimal logging for maximum speed
logging.basicConfig(level=logging.ERROR)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global Task Dictionary
BATCH_TASKS = {}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    """Smartly resolves any Telegram identifier to a Chat ID."""
    link_or_id = link_or_id.strip()
    
    # 1. Numeric ID
    if re.match(r"^-?\d+$", link_or_id):
        return int(link_or_id)
    
    # 2. Private Link (t.me/c/...)
    if "t.me/c/" in link_or_id:
        try:
            parts = link_or_id.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None

    # 3. Invite Links (Auto-Join)
    if any(x in link_or_id for x in ["t.me/+", "t.me/joinchat/"]):
        try:
            chat = await userbot.join_chat(link_or_id)
            return chat.id
        except UserAlreadyParticipant:
            chat = await userbot.get_chat(link_or_id)
            return chat.id
        except: return None

    # 4. Public Links
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

# ================= FORWARDING ENGINE =================

async def run_batch_worker(task_id):
    """The engine that keeps the process alive with a 2-second pulse."""
    task = BATCH_TASKS[task_id]
    
    while BATCH_TASKS.get(task_id) and BATCH_TASKS[task_id]['running']:
        try:
            # Fetch the message
            msg = await userbot.get_messages(task['source'], task['current'])
            
            # If message doesn't exist (yet), wait for 2 seconds and retry
            if not msg or msg.empty:
                await asyncio.sleep(2)
                continue

            if not msg.service:
                try:
                    await userbot.copy_message(task['dest'], task['source'], msg.id)
                    # Fixed 2-second delay between successful forwards
                    await asyncio.sleep(2)
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                except Exception:
                    pass # Skip deleted/restricted content

            task['current'] += 1

        except Exception:
            await asyncio.sleep(3) # Anti-crash safety

@userbot.on_message(filters.incoming)
async def realtime_listener(client, message):
    """Real-time listener for instant forwarding of new posts."""
    for tid, task in BATCH_TASKS.items():
        if task['running'] and message.chat.id == task['source']:
            # If message ID is ahead of our batch current index, forward it immediately
            if message.id >= task['current']:
                try:
                    await userbot.copy_message(task['dest'], task['source'], message.id)
                except: pass

# ================= BOT HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        "I am your **High-Performance Multi-Forwarder**.\n"
        "I can transfer messages from restricted channels and private links "
        "with a steady 2-second interval.\n\n"
        "🚀 **System Status:** `Ready & Stable`"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create New Batch", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Active Batches", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def query_processor(client, query: CallbackQuery):
    uid = query.from_user.id

    if query.data == "new_batch":
        await query.message.delete()
        
        # 1. Ask Source
        src_ask = await client.ask(uid, "📤 **Step 1:** Send the **Source Link or ID**.\n(Example: `https://t.me/c/123/10`)", timeout=60)
        source_chat = await resolve_chat(src_ask.text)
        start_id = extract_msg_id(src_ask.text)
        
        if not source_chat:
            return await client.send_message(uid, "❌ **Error:** Source not found. Ensure the Userbot is a member of that chat.")

        # 2. Ask Destination
        dest_ask = await client.ask(uid, "📥 **Step 2:** Send the **Destination Link or ID**.\n(Example: `-100...`)", timeout=60)
        dest_chat = await resolve_chat(dest_ask.text)
        
        if not dest_chat:
            return await client.send_message(uid, "❌ **Error:** Destination unreachable. Check if Userbot has joined.")

        # Task Setup
        tid = random.randint(100, 999)
        BATCH_TASKS[tid] = {
            "source": source_chat, "dest": dest_chat,
            "current": start_id, "running": True, "user_id": uid
        }
        
        asyncio.create_task(run_batch_worker(tid))
        await client.send_message(uid, f"✅ **Batch {tid} Initiated!**\n\nYour messages are now being forwarded at a 2-second pulse. Enjoy! ✨")

    elif query.data == "view_status":
        active = [f"🔹 **ID:** `{tid}` | **Msg:** `{data['current']}`" for tid, data in BATCH_TASKS.items() if data['running'] and data['user_id'] == uid]
        if not active:
            return await query.answer("No active tasks found!", show_alert=True)
        
        txt = "📋 **Current Active Tasks:**\n\n" + "\n".join(active)
        btns = [[InlineKeyboardButton(f"🛑 Terminate {t.split('`')[1]}", callback_data=f"stop_{t.split('`')[1]}")] for t in active]
        btns.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_home")])
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("stop_"):
        tid = int(query.data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.answer(f"Task {tid} terminated.", show_alert=True)
            await query.message.edit_text(f"🛑 **Batch {tid}** has been stopped successfully.")

    elif query.data == "back_home":
        await start_handler(client, query.message)

# ================= SYSTEM BOOT =================

async def main():
    print("--- Starting System ---")
    await app.start()
    await userbot.start()
    print("--- Bot & Userbot are Online ---")
    await idle()

if __name__ == "__main__":
    from pyromod import listen # Required: pip install pyromod
    app.run(main())
    
