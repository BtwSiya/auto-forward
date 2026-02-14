import asyncio
import logging
import re
import random
import os
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    FloodWait, RPCError, UserAlreadyParticipant, 
    ChatForwardsRestricted, InviteHashExpired
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

# ================= CONFIGURATION =================
API_ID = 21705136
API_HASH = "78730e89d196e160b0f1992018c6cb19"
BOT_TOKEN = "8572528424:AAG3Bk4L-xnpmu2IWMfRS_m5AG8foG7cPRc"
SESSION_STRING = "BQFGCokAgeUYbfqZyyM_tUlZOL9e4XM-eNqZX7_433fLwjvGB4SKL2YC6GBy-7S8ySKF4mwvaFE3FoUPQBrptI68vigVx7RBBwcUlV8LjHDK7CDuyin3nF8vIusS6g3ujLgQBBKajb7IhGPQVOMm-9q2kdROazENzXx-BHPVr3XaSeLM3gtPnY1T_y_RukGosNOfHTfwMkD0oS7fj0zl6KNwO4OgQEAFzTXmfpw9cAW9hCItiT16Q9UE9E75IhekfoPxCSVgwYt35fN7FCPzz8hQNIQwSLikifoeb5XAYSBGHwOnwIdiiovPwLZ9cB9tbEE4utODrHCqZLgVNhcTcjRcVod2MwAAAAF5efmpAA"

logging.basicConfig(level=logging.ERROR)
app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

BATCH_TASKS = {}
USER_STATE = {}
PROCESSED_GROUPS = set()

# ================= UTILS =================

async def resolve_chat(link):
    link = str(link).strip().rstrip("/")
    if re.match(r"^-?\d+$", link): return int(link)
    if "t.me/c/" in link:
        try:
            parts = link.split('/')
            return int("-100" + parts[parts.index('c') + 1])
        except: return None
    if "t.me/+" in link or "joinchat" in link:
        try:
            try: await userbot.join_chat(link)
            except UserAlreadyParticipant: pass
            chat = await userbot.get_chat(link)
            return chat.id
        except: return None
    try:
        username = link.split('/')[-1]
        chat = await userbot.get_chat(username)
        return chat.id
    except: return None

async def get_thumb(msg):
    try:
        if msg.video and msg.video.thumbs:
            return await userbot.download_media(msg.video.thumbs[0].file_id)
        if msg.document and msg.document.thumbs:
            return await userbot.download_media(msg.document.thumbs[0].file_id)
    except: pass
    return None

# ================= CORE ENGINE =================

async def update_report(task_id, activity):
    t = BATCH_TASKS.get(task_id)
    if not t: return
    text = (
        f"📊 **Live Task Report: {task_id}**\n\n"
        f"✅ **Success:** `{t['total']}`\n"
        f"📍 **Current ID:** `{t['current']}`\n"
        f"⚡ **Activity:** `{activity}`\n"
        f"📢 **Status:** {'🟢 Running' if t['running'] else '🛑 Stopped'}"
    )
    try: await app.edit_message_text(t['user_id'], t['log_msg_id'], text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 Stop Task", callback_data=f"kill_{task_id}")]]))
    except: pass

async def run_worker(task_id):
    while task_id in BATCH_TASKS and BATCH_TASKS[task_id]['running']:
        t = BATCH_TASKS[task_id]
        try:
            msg = await userbot.get_messages(t['source'], t['current'])
            
            if not msg or msg.empty:
                # Live Monitoring: Check if we reached the end
                history = await userbot.get_history(t['source'], limit=1)
                if history and t['current'] > history[0].id:
                    await update_report(task_id, "Waiting for new messages...")
                    await asyncio.sleep(10)
                    continue
                t['current'] += 1
                continue

            if msg.service:
                t['current'] += 1
                continue

            # GROUPING/ALBUM LOGIC
            if msg.media_group_id:
                if msg.media_group_id in PROCESSED_GROUPS:
                    t['current'] += 1
                    continue
                
                try:
                    album = await userbot.get_media_group(t['source'], msg.id)
                    PROCESSED_GROUPS.add(msg.media_group_id)
                    
                    try:
                        await userbot.copy_media_group(t['dest'], t['source'], msg.id)
                        t['total'] += len(album)
                    except ChatForwardsRestricted:
                        # Restricted Content Bypass
                        media_list = []
                        files = []
                        for m in album:
                            path = await userbot.download_media(m)
                            files.append(path)
                            thumb = await get_thumb(m)
                            if thumb: files.append(thumb)
                            
                            if m.photo: media_list.append(InputMediaPhoto(path, caption=m.caption))
                            elif m.video: media_list.append(InputMediaVideo(path, caption=m.caption, thumb=thumb, duration=m.video.duration, width=m.video.width, height=m.video.height, supports_streaming=True))
                            elif m.document: media_list.append(InputMediaDocument(path, caption=m.caption, thumb=thumb))
                        
                        await userbot.send_media_group(t['dest'], media=media_list)
                        t['total'] += len(album)
                        for f in files: 
                            if f and os.path.exists(f): os.remove(f)

                    t['current'] = max([m.id for m in album]) + 1
                    continue
                except: pass

            # SINGLE MESSAGE
            try:
                if msg.text:
                    await userbot.send_message(t['dest'], msg.text, entities=msg.entities)
                else:
                    try:
                        await userbot.copy_message(t['dest'], t['source'], msg.id)
                    except ChatForwardsRestricted:
                        path = await userbot.download_media(msg)
                        thumb = await get_thumb(msg)
                        if msg.photo: await userbot.send_photo(t['dest'], path, caption=msg.caption)
                        elif msg.video: await userbot.send_video(t['dest'], path, caption=msg.caption, thumb=thumb, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, supports_streaming=True)
                        elif msg.document: await userbot.send_document(t['dest'], path, caption=msg.caption, thumb=thumb)
                        if path and os.path.exists(path): os.remove(path)
                        if thumb and os.path.exists(thumb): os.remove(thumb)
                t['total'] += 1
            except: pass

            t['current'] += 1
            await update_report(task_id, "Forwarding...")
            await asyncio.sleep(1.5)

        except FloodWait as e: await asyncio.sleep(e.value + 5)
        except Exception as e:
            await asyncio.sleep(5)

# ================= HANDLERS =================

@app.on_message(filters.command("start") & filters.private)
async def start(c, m):
    USER_STATE[m.from_user.id] = {"step": "SOURCE"}
    await m.reply("🔗 **Step 1:**\nSend Source Link.")

@app.on_callback_query(filters.regex("^kill_"))
async def kill(c, q):
    tid = int(q.data.split("_")[1])
    if tid in BATCH_TASKS: BATCH_TASKS[tid]['running'] = False
    await q.answer("Task Stopped", show_alert=True)

@app.on_message(filters.private & ~filters.command("start"))
async def steps(c, m):
    uid = m.from_user.id
    if uid not in USER_STATE: return
    
    if USER_STATE[uid]["step"] == "SOURCE":
        res = await resolve_chat(m.text)
        if not res: return await m.reply("❌ **Invalid Source!**")
        
        start_id = 1
        if "/" in m.text and m.text.split('/')[-1].isdigit():
            start_id = int(m.text.split('/')[-1])
            
        USER_STATE[uid].update({"source": res, "start": start_id, "step": "DEST"})
        await m.reply("✅ **Source Found!**\n\n📥 **Step 2:**\nSend Destination Link.")

    elif USER_STATE[uid]["step"] == "DEST":
        res = await resolve_chat(m.text)
        if not res: return await m.reply("❌ **Invalid Destination!**")
        
        task_id = random.randint(1000, 9999)
        log = await m.reply("🚀 **Initializing...**")
        BATCH_TASKS[task_id] = {
            "source": USER_STATE[uid]['source'], "dest": res, "current": USER_STATE[uid]['start'],
            "total": 0, "running": True, "user_id": uid, "log_msg_id": log.id
        }
        del USER_STATE[uid]
        asyncio.create_task(run_worker(task_id))

async def main():
    await app.start()
    await userbot.start()
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
                        
