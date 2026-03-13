import asyncio
import sys
import os
import json
import logging
from datetime import datetime
from math import ceil
from pathlib import Path

# ============ PATCH PARA PYTHON 3.14 ============
if sys.version_info >= (3, 14):
    print("🔧 Aplicando parche para Python 3.14...")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    import typing
    if not hasattr(typing.Union, '__module__'):
        typing.Union.__module__ = 'typing'

# ============ IMPORTS ============
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

# ============ SERVIDOR WEB ============
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        response = "🤖 Bot is running"
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"✅ Health server running on port {port}")
    server.serve_forever()

health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

# ============ CONFIGURACIÓN ============
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 🔐 TUS VARIABLES
API_ID = 14681595
API_HASH = "a86730aab5c59953c424abb4396d32d5"
BOT_TOKEN = "8728854601:AAFkSuFMdaNP0OWP5EYfLg9f-hgds-IQ0Pc"
OWNER_ID = 7970466590

# 📢 CANAL
STATUS_CHANNEL_ID = "@ecanarender"
STATUS_MESSAGE_ID = 2

# ⚙️ Configuración
CHECK_INTERVAL_MINUTES = 60
PROJECTS_FILE = "projects.json"

# Clientes
http_client = httpx.AsyncClient(timeout=10)

app = Client(
    "render_manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/opt/render/project/src"
)


# ============ GESTIÓN DE PROYECTOS ============
def load_projects() -> dict:
    if Path(PROJECTS_FILE).exists():
        try:
            with open(PROJECTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_projects(projects: dict) -> bool:
    try:
        with open(PROJECTS_FILE, 'w') as f:
            json.dump(projects, f, indent=2)
        return True
    except:
        return False

PROJECTS = load_projects()


# ============ FUNCIONES PRINCIPALES ============
async def check_app_status(app_url: str) -> str:
    try:
        r = await http_client.get(app_url, follow_redirects=True)
        return "Online" if r.status_code == 200 else f"Unstable ({r.status_code})"
    except:
        return "Down"

async def check_all_and_update_channel():
    logger.info("🔍 Running periodic check...")
    for name in PROJECTS:
        status = await check_app_status(PROJECTS[name]["app_url"])
        logger.info(f"  {name}: {status}")
    
    text = f"📊 Render Monitor\n🕒 {datetime.now()}\n📁 Projects: {len(PROJECTS)}"
    try:
        await app.edit_message_text(STATUS_CHANNEL_ID, STATUS_MESSAGE_ID, text)
        logger.info("✅ Channel updated")
    except Exception as e:
        logger.error(f"❌ Channel error: {e}")


# ============ COMANDOS CON DIAGNÓSTICO ============
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    logger.info(f"🔥🔥🔥 RECEIVED /start from {message.from_user.id}")
    logger.info(f"Message: {message.text}")
    
    await message.reply(
        f"✅ Bot funcionando!\n\n"
        f"Tu ID: {message.from_user.id}\n"
        f"Username: @{message.from_user.username}\n"
        f"Es admin: {message.from_user.id == OWNER_ID}"
    )

@app.on_message(filters.private)
async def echo_all(client: Client, message: Message):
    logger.info(f"📨 RECEIVED: {message.text} from {message.from_user.id}")
    await message.reply(f"Eco: {message.text}")


# ============ MAIN ============
def start_scheduler(loop):
    scheduler = AsyncIOScheduler()
    async def run_check():
        await check_all_and_update_channel()
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(run_check(), loop),
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES)
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started")

async def main():
    logger.info("🚀 Starting bot...")
    
    await app.start()
    logger.info("🤖 Bot started")
    
    me = await app.get_me()
    logger.info(f"🤖 Bot @{me.username} (ID: {me.id})")
    
    start_scheduler(asyncio.get_running_loop())
    await check_all_and_update_channel()
    
    logger.info("📡 Bot is running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped")