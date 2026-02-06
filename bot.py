import asyncio
import logging
import re
import random
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant, MessageNotModified, ChannelInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAErREWZ0rxRYnzyJw06dRgOsrwQRcEhlkc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

# Logging setup to catch errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global Storage
BATCH_TASKS = {} # {task_id: {data}}
USER_STATE = {}

# ================= UTILS =================

async def resolve_chat(link_or_id: str):
    """Smartly resolves Chat ID from Links, Usernames, or IDs."""
    link_or_id = str(link_or_id).strip()
    
    # Clean the link if it contains message ID (remove /123 at the end)
    if "/" in link_or_id and link_or_id.split("/")[-1].isdigit():
        parts = link_or_id.split("/")
        # Reconstruct link without the message ID part
        link_or_id = "/".join(parts[:-1])

    try:
        if re.match(r"^-?\d+$", link_or_id):
            return int(link_or_id)
        
        if "t.me/c/" in link_or_id: # Private Channel Link
            chat_id = int("-100" + link_or_id.split("t.me/c/")[1].split("/")[0])
            return chat_id

        if "t.me/+" in link_or_id or "joinchat" in link_or_id:
            try:
                chat = await userbot.join_chat(link_or_id)
                return chat.id
            except UserAlreadyParticipant:
                # If already joined, we need to fetch the chat to get ID
                # This is tricky for invite links, usually we need to peek or get cached peer
                # For simplicity, ask user for ID if join fails, or try get_chat
                pass
        
        if "t.me/" in link_or_id:
            username = link_or_id.split("t.me/")[-1].split("/")[0]
            chat = await userbot.get_chat(username)
            return chat.id
            
    except Exception as e:
        logger.error(f"Resolve Error: {e}")
        return None
    return None

def get_link_msg_id(link: str):
    """Extracts Message ID if present in link, else returns None."""
    if "/" in link and link.split("/")[-1].isdigit():
        return int(link.split("/")[-1])
    return None

# ================= LIVE MONITOR ENGINE =================

async def update_log(task_id):
    """Updates the progress message in DM."""
    task = BATCH_TASKS.get(task_id)
    if not task: return
    
    try:
        status_text = "🟢 **Running**" if task['running'] else "🔴 **Stopped**"
        log_text = (
            f"📊 **Live Task Report: {task_id}**\n\n"
            f"🆔 **Source ID:** `{task['source']}`\n"
            f"🎯 **Dest ID:** `{task['dest']}`\n"
            f"🔢 **Processing Msg ID:** `{task['current']}`\n"
            f"✅ **Successfully Forwarded:** `{task['total']}`\n"
            f"⏭️ **Skipped/Deleted:** `{task['skipped']}`\n\n"
            f"⏳ *Status: {status_text}*"
        )
        await app.edit_message_text(
            task['user_id'], 
            task['log_msg_id'], 
            log_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task {task_id}", callback_data=f"kill_{task_id}")]])
        )
    except (MessageNotModified, RPCError): 
        pass

async def run_batch_worker(task_id):
    """The Engine: Handles backlog and real-time syncing."""
    logger.info(f"Task {task_id} started.")
    
    consecutive_errors = 0
    
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        task = BATCH_TASKS[task_id]
        
        try:
            # Try to fetch the message
            try:
                msg = await userbot.get_messages(task['source'], task['current'])
            except RPCError:
                msg = None

            # CASE 1: Message does not exist or is deleted
            if not msg or msg.empty:
                task['skipped'] += 1
                task['current'] += 1
                consecutive_errors += 1
                
                # If we hit 50 consecutive empty messages, assume we reached the end
                # and wait for new messages instead of looping fast.
                if consecutive_errors > 50:
                    await asyncio.sleep(5) 
                continue 

            # CASE 2: Message exists
            consecutive_errors = 0 # Reset error counter
            
            if not msg.service: # Skip service messages (like 'User joined')
                try:
                    # COPY MESSAGE (Works for images, videos, texts, files)
                    if msg.media_group_id:
                        # Simple handling for albums: Copy one by one or use copy_media_group if implemented
                        # Standard copy_message handles single items well. 
                        # For simplicity in V3, we use copy_message per part to ensure order.
                        await userbot.copy_message(task['dest'], task['source'], msg.id)
                    else:
                        await userbot.copy_message(task['dest'], task['source'], msg.id)
                    
                    task['total'] += 1
                    # Update Log every 5 successful forwards to avoid rate limit
                    if task['total'] % 5 == 0:
                        await update_log(task_id)
                        
                    # DELAY: 3 Seconds as requested
                    await asyncio.sleep(3)
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait: Sleeping {e.value}s")
                    await update_log(task_id) # Force update log to show status
                    await asyncio.sleep(e.value + 5)
                except RPCError as e:
                    logger.error(f"Copy Error on {task['current']}: {e}")
                    task['skipped'] += 1

            # Move to next message
            task['current'] += 1
            
        except Exception as e:
            logger.error(f"Worker Exception: {e}")
            await asyncio.sleep(5)

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    USER_STATE[message.from_user.id] = None
    text = (
        "🚀 **Pro Media Forwarder V3.1**\n\n"
        "✅ **Supports:** Channel -> Channel | Group -> Channel\n"
        "✅ **Smart Resume:** Auto-detects Start ID\n"
        "✅ **Safety:** 3s Delay + FloodWait Handler\n"
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
        await query.message.edit_text(
            "🔗 **Step 1: Source**\n\n"
            "Send the **Link** of the Channel/Group.\n"
            "Example: `https://t.me/my_channel` or `https://t.me/my_channel/105`"
        )

    elif data == "view_status":
        active_btns = []
        for tid, t_info in BATCH_TASKS.items():
            if t_info['running'] and t_info['user_id'] == uid:
                active_btns.append([InlineKeyboardButton(f"🛑 Stop {tid} (Msg: {t_info['current']})", callback_data=f"kill_{tid}")])
        
        if not active_btns:
            return await query.answer("No running tasks.", show_alert=True)
        
        active_btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text("📋 **Task Manager:**", reply_markup=InlineKeyboardMarkup(active_btns))

    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await update_log(tid) # Final update
            await query.answer(f"Task {tid} Terminated!", show_alert=True)
            del BATCH_TASKS[tid]
        else:
            await query.answer("Task already finished or invalid.", show_alert=True)

    elif data == "back_home":
        await start_handler(client, query.message)

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE or not USER_STATE[uid]: return

    step = USER_STATE[uid]["step"]
    user_input = message.text

    # --- STEP 1: SOURCE ---
    if step == "SOURCE":
        msg = await message.reply("🔍 **Checking Source...**")
        
        # 1. Try to resolve chat
        source_id = await resolve_chat(user_input)
        
        if not source_id:
            return await msg.edit("❌ **Invalid Source!**\nMake sure the Userbot has joined the chat/channel.\nTry sending the Link again.")
        
        # 2. Check if user provided a specific message ID in link
        start_id = get_link_msg_id(user_input)
        
        # Save state
        USER_STATE[uid]["source_id"] = source_id
        
        if start_id:
            # ID found in link, skip asking
            USER_STATE[uid]["start_id"] = start_id
            USER_STATE[uid]["step"] = "DEST"
            await msg.edit(f"✅ Source Found!\nStarting from Message ID: `{start_id}`\n\n📥 **Step 2:** Send Destination Channel ID/Link.")
        else:
            # ID NOT found, ask user
            USER_STATE[uid]["step"] = "ASK_ID"
            await msg.edit("🔢 **Start Point Required**\n\nYou sent a channel link without a message ID.\n\n**Enter the Message ID to start from:**\n(e.g., send `1` for beginning, or `1000` for recent)")

    # --- STEP 1.5: ASK ID (If not in link) ---
    elif step == "ASK_ID":
        try:
            start_id = int(user_input.strip())
            USER_STATE[uid]["start_id"] = start_id
            USER_STATE[uid]["step"] = "DEST"
            await message.reply(f"✅ Starting from ID: `{start_id}`\n\n📥 **Step 2:** Send Destination Channel ID/Link.")
        except ValueError:
            await message.reply("❌ **Invalid Number!** Please send a numeric Message ID (e.g., `100`).")

    # --- STEP 2: DESTINATION ---
    elif step == "DEST":
        msg = await message.reply("🔍 **Checking Destination...**")
        dest_id = await resolve_chat(user_input)
        
        if not dest_id:
            return await msg.edit("❌ **Invalid Destination!**\nMake sure the Bot/Userbot is admin there.")

        # FINAL SETUP
        task_data = USER_STATE[uid]
        task_id = random.randint(1000, 9999)
        
        BATCH_TASKS[task_id] = {
            "source": task_data['source_id'],
            "dest": dest_id,
            "current": task_data['start_id'],
            "total": 0,
            "skipped": 0,
            "running": True,
            "user_id": uid,
            "log_msg_id": msg.id # Use this msg for logs
        }
        
        await msg.edit(f"🚀 **Task {task_id} Initialized!**\n\nSource: `{task_data['source_id']}`\nDest: `{dest_id}`\nStart Msg: `{task_data['start_id']}`\n\n*Forwarding will start in 3s...*")
        
        USER_STATE[uid] = None # Clear state
        
        # Start Worker
        asyncio.create_task(run_batch_worker(task_id))

# ================= BOOT =================

async def main():
    print("--- Connecting Clients ---")
    await app.start()
    await userbot.start()
    print("--- Pro Forwarder V3 Ready ---")
    await idle()
    await app.stop()
    await userbot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
                
