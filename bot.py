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
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, InputMediaVideo, InputMediaDocument

# ================= CONFIGURATION =================
# SECURITY WARNING: Aapne API Keys public kar di hain. Is code ke chalne ke baad keys reset karein.
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
PROCESSED_GROUPS = {} # To fix 3-4 times repeat issue

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
            try:
                chat = await userbot.join_chat(link_or_id)
                return chat.id
            except UserAlreadyParticipant:
                chat = await userbot.get_chat(link_or_id)
                return chat.id
        else:
            username = link_or_id.split('/')[-1]
            try: await userbot.join_chat(username)
            except: pass
            chat = await userbot.get_chat(username)
            return chat.id
    except Exception: return None

# ================= CORE ENGINE (FIXED) =================

async def update_live_report(task_id, current_activity="Running"):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    
    status = "🟢 Running" if t['running'] else "🛑 Stopped"
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"❌ **Failed:** `{t['failed']}`\n"
        f"⏭️ **Skipped:** `{t['skipped']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n\n"
        f"⚡ **Activity:** `{current_activity}`\n"
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
                    # ALBUM HANDLING (Fixing Duplicate Sending & Metadata)
                    if msg.media_group_id:
                        if msg.media_group_id in PROCESSED_GROUPS:
                            t['current'] += 1
                            continue # Skip already processed album part
                        
                        await update_live_report(task_id, "Processing Album (Grouping)...")
                        try:
                            # Try copy first
                            await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                            t['total'] += 1
                            PROCESSED_GROUPS[msg.media_group_id] = True
                        except ChatForwardsRestricted:
                            # Download & Upload bypass for Albums (Fix Black Screen)
                            await update_live_report(task_id, "Downloading Restricted Album...")
                            album = await userbot.get_media_group(t['source'], msg.id)
                            media_group = []
                            files_to_delete = []
                            
                            for m in album:
                                path = await userbot.download_media(m)
                                if path:
                                    files_to_delete.append(path)
                                    # Handle Thumbnail and Metadata for Albums
                                    thumb_path = None
                                    if m.photo:
                                        media_group.append(InputMediaPhoto(path, caption=m.caption))
                                    elif m.video:
                                        # Extract Metadata
                                        duration = m.video.duration or 0
                                        width = m.video.width or 0
                                        height = m.video.height or 0
                                        if m.video.thumbs:
                                            try:
                                                thumb_path = await userbot.download_media(m.video.thumbs[0].file_id)
                                                if thumb_path: files_to_delete.append(thumb_path)
                                            except: pass
                                        
                                        media_group.append(InputMediaVideo(
                                            path, 
                                            caption=m.caption,
                                            duration=duration,
                                            width=width,
                                            height=height,
                                            thumb=thumb_path,
                                            supports_streaming=True
                                        ))
                                    elif m.document:
                                        media_group.append(InputMediaDocument(path, caption=m.caption))
                            
                            if media_group:
                                await update_live_report(task_id, "Uploading Album...")
                                await userbot.send_media_group(t['dest'], media=media_group)
                                t['total'] += 1
                                PROCESSED_GROUPS[msg.media_group_id] = True
                            
                            # Cleanup
                            for p in files_to_delete:
                                if os.path.exists(p): os.remove(p)
                    
                    # SINGLE MESSAGE HANDLING (Fixing Black Screen & Duration)
                    else:
                        try:
                            await userbot.copy_message(t['dest'], t['source'], msg.id)
                            t['total'] += 1
                        except ChatForwardsRestricted:
                            await update_live_report(task_id, "File Detected: Downloading...")
                            path = await userbot.download_media(msg)
                            
                            if path:
                                await update_live_report(task_id, "Uploading to Destination...")
                                
                                if msg.photo:
                                    await userbot.send_photo(t['dest'], path, caption=msg.caption)
                                elif msg.video:
                                    # FIX: Extract Metadata and Thumbnail
                                    duration = msg.video.duration or 0
                                    width = msg.video.width or 0
                                    height = msg.video.height or 0
                                    thumb_path = None
                                    
                                    if msg.video.thumbs:
                                        try:
                                            thumb_path = await userbot.download_media(msg.video.thumbs[0].file_id)
                                        except: pass

                                    await userbot.send_video(
                                        t['dest'], 
                                        path, 
                                        caption=msg.caption, 
                                        supports_streaming=True,
                                        duration=duration,
                                        width=width,
                                        height=height,
                                        thumb=thumb_path
                                    )
                                    
                                    if thumb_path and os.path.exists(thumb_path):
                                        os.remove(thumb_path)
                                        
                                elif msg.document:
                                    # Try to preserve thumb for documents too if available
                                    thumb_path = None
                                    if msg.document.thumbs:
                                        try:
                                            thumb_path = await userbot.download_media(msg.document.thumbs[0].file_id)
                                        except: pass
                                        
                                    await userbot.send_document(
                                        t['dest'], 
                                        path, 
                                        caption=msg.caption,
                                        thumb=thumb_path
                                    )
                                    if thumb_path and os.path.exists(thumb_path):
                                        os.remove(thumb_path)
                                else:
                                    # Fallback for voice/audio
                                    if msg.voice: await userbot.send_voice(t['dest'], path, caption=msg.caption)
                                    elif msg.audio: await userbot.send_audio(t['dest'], path, caption=msg.caption)
                                    else: await userbot.send_document(t['dest'], path, caption=msg.caption)

                                if os.path.exists(path): os.remove(path)
                                t['total'] += 1
                            else: raise Exception("Download Failed")
                            
                except Exception as e:
                    t['failed'] += 1
                    t['last_error'] = str(e)[:100]

            t['current'] += 1
            await update_live_report(task_id, "Waiting...")
            await asyncio.sleep(3.5) # Anti-flood delay

        except FloodWait as e:
            await asyncio.sleep(e.value + 5)
        except Exception as e:
            t['last_error'] = f"Loop: {str(e)[:50]}"
            await asyncio.sleep(5)

# ================= UI HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    text = (
        "🚀 **Advanced Media Forwarder **\n\n"
        "✅ Yoo Baby \n"
        "✅ **Fix:** Proper Video Duration & Thumbnails\n"
        "✅ Live Activity Report\n"
        "✅ Unlimited File Size Support"
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Start Forwarding", callback_data="new_batch")],
        [InlineKeyboardButton("📊 Active Tasks", callback_data="view_status")]
    ])
    await message.reply_text(text, reply_markup=btns)

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    uid, data = query.from_user.id, query.data
    if data == "new_batch":
        USER_STATE[uid] = {"step": "SOURCE"}
        await query.message.edit_text("🔗 **Step 1:**\nSend Source Channel Link.")
    elif data == "view_status":
        active_btns = [[InlineKeyboardButton(f"🛑 Stop Task {tid}", callback_data=f"kill_{tid}")] 
                       for tid, t in BATCH_TASKS.items() if t['running'] and t['user_id'] == uid]
        if not active_btns: return await query.answer("No active tasks!", show_alert=True)
        await query.message.edit_text("📋 **Active Monitor:**", reply_markup=InlineKeyboardMarkup(active_btns))
    elif data.startswith("kill_"):
        tid = int(data.split("_")[1])
        if tid in BATCH_TASKS:
            BATCH_TASKS[tid]['running'] = False
            await query.message.edit_text(f"✅ **Task {tid} Stopped.**")

@app.on_message(filters.private & ~filters.command("start"))
async def state_manager(client, message):
    uid = message.from_user.id
    if uid not in USER_STATE: return
    step = USER_STATE[uid]["step"]
    
    if step == "SOURCE":
        msg = await message.reply("🔍 Checking Source...")
        source = await resolve_chat(message.text)
        if not source: return await msg.edit("❌ **Invalid Source!**")
        start_id = int(message.text.split("/")[-1]) if "/" in message.text and message.text.split("/")[-1].isdigit() else 1
        USER_STATE[uid] = {"step": "DEST", "source": source, "start": start_id}
        await msg.edit(f"✅ **Source Found!**\n\n📥 **Step 2:**\nSend Destination Channel Link.")
    elif step == "DEST":
        msg = await message.reply("🔍 Checking Destination...")
        dest = await resolve_chat(message.text)
        if not dest: return await msg.edit("❌ **Invalid Destination!**")
        task_id = random.randint(1000, 9999)
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": dest, "current": USER_STATE[uid]['start'],
            "total": 0, "failed": 0, "skipped": 0, "running": True,
            "user_id": uid, "log_msg_id": msg.id, "last_error": "None"
        }
        del USER_STATE[uid]
        await msg.edit(f"🚀 **Task {task_id} Initialized!**")
        asyncio.create_task(run_batch_worker(task_id))

async def main():
    await app.start()
    await userbot.start()
    print("--- Pro Forwarder V6 Ready (Metadata Fixed) ---")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
            
