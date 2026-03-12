import os
import asyncio
import logging
from datetime import datetime
from math import ceil

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.enums import ParseMode
from projects import PROJECTS

load_dotenv()
logging.basicConfig(level=logging.INFO)


API_ID = int(os.getenv("API_ID", "14681595"))
API_HASH = os.getenv("API_HASH","a86730aab5c59953c424abb4396d32d5
")
BOT_TOKEN = os.getenv("BOT_TOKEN","8728854601:AAFkSuFMdaNP0OWP5EYfLg9f-hgds-IQ0Pc")
OWNER_ID = int(os.getenv("OWNER_ID", "7970466590"))

STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "-1003799101536"))
STATUS_MESSAGE_ID = int(os.getenv("STATUS_MESSAGE_ID", "2"))

CHECK_INTERVAL_MINUTES = 60
PAGE_SIZE = 10


HTTP_TIMEOUT = 10
http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
app = Client("render_manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


async def check_app_status(app_url: str) -> str:
    try:
        r = await http_client.get(app_url)
        if r.status_code == 200:
            return "Online"
        else:
            return f"Unstable ({r.status_code})"
    except Exception:
        return "Down"

async def trigger_render_deploy(deploy_url: str) -> str:
    try:
        r = await http_client.post(deploy_url, timeout=30)
        if r.status_code == 200:
            return "Redeploy triggered ✅"
        else:
            return f"Deploy failed ({r.status_code})"
    except Exception as e:
        return f"Error: {e}"

def build_status_page(project_names, statuses):
    total = len(project_names)
    pages = max(1, ceil(total / PAGE_SIZE))
    lines = []

    for idx, name in enumerate(project_names, start=1):
        status = statuses.get(name, "Unknown")
        emoji = "🟢" if status == "Online" else ("🟡" if status.startswith("Unstable") else "🔴")
        lines.append(f"{idx}. <b>{name}</b> — {emoji} {status}")

    header = (
        f"📊 <b>Project Status</b>\n"
        f"Last checked: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
    )
    body = "\n".join(lines) if lines else "No projects to display."
    footer = f"\n\nTotal projects: {total}"
    return header + body + footer


async def check_all_and_update_channel(send_notifications: bool = True):
    logging.info("Running periodic check_all_and_update_channel()")
    project_names = list(PROJECTS.keys())
    statuses = {}
    redeploy_results = {}

    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])

    # Auto redeploy if down
    for name, status in statuses.items():
        if status == "Down":
            result = await trigger_render_deploy(PROJECTS[name]["deploy_url"])
            redeploy_results[name] = result
            logging.warning(f"⚠️ {name} was Down — {result}")

    text = build_status_page(project_names, statuses)
    try:
        await app.edit_message_text(
            chat_id=STATUS_CHANNEL_ID,
            message_id=STATUS_MESSAGE_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        logging.info("✅ Channel status message updated.")
    except Exception as e:
        logging.error(f"Failed to edit channel message: {e}")

    return statuses, redeploy_results


scheduler = AsyncIOScheduler()

def start_scheduler(loop):
    async def run_periodic_check():
        await check_all_and_update_channel(send_notifications=True)

    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(run_periodic_check(), loop),
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
        id="auto_check_job",
        replace_existing=True,
    )
    scheduler.start()
    logging.info(f"✅ Scheduler started — checking every {CHECK_INTERVAL_MINUTES} minute(s).")


async def main():
    await app.start()
    logging.info("🤖 Bot started.")

    loop = asyncio.get_running_loop()
    start_scheduler(loop)

    await check_all_and_update_channel(send_notifications=False)

    logging.info("Entering idle loop...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped manually.")
