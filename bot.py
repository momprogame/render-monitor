import asyncio
import sys
import os
import json
import logging
from datetime import datetime
from math import ceil
from pathlib import Path

# ============ PATCH MEJORADO PARA PYTHON 3.14 ============
# ESTO DEBE IR ANTES DE CUALQUIER OTRO IMPORT
if sys.version_info >= (3, 14):
    print("🔧 Aplicando parche mejorado para Python 3.14...")
    
    # Crear event loop si no existe
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Parche para typing.Union
    import typing
    if not hasattr(typing.Union, '__module__'):
        typing.Union.__module__ = 'typing'
    
    # Parche para asyncio
    if not hasattr(asyncio, 'get_event_loop'):
        asyncio.get_event_loop = asyncio.get_running_loop

# ============ IMPORTS ============
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

# ============ SERVIDOR WEB SIMPLE ============
# Usamos http.server en lugar de aiohttp para evitar problemas
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        if self.path == '/status':
            html = f"""
            <html>
                <head><title>Render Monitor Bot</title></head>
                <body style="font-family: Arial; padding: 20px;">
                    <h1>🤖 Render Monitor Bot</h1>
                    <p>✅ Bot is running</p>
                    <p>📁 Projects: {len(PROJECTS) if 'PROJECTS' in globals() else 0}</p>
                    <p>⏱️ Check interval: 60 minutes</p>
                    <p>📢 Channel: @ecanarender</p>
                    <p><small>Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
                </body>
            </html>
            """
            self.wfile.write(html.encode())
        else:
            self.wfile.write(b"🤖 Bot is running")
    
    def log_message(self, format, *args):
        # Silenciar logs del servidor
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"✅ Health server running on port {port}")
    server.serve_forever()

# Iniciar servidor en un hilo separado
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
PAGE_SIZE = 10
HTTP_TIMEOUT = 10
DEPLOY_TIMEOUT = 30
PROJECTS_FILE = "projects.json"

# Clientes
http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

app = Client(
    "render_manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============ GESTIÓN DE PROYECTOS ============
def load_projects() -> dict:
    if Path(PROJECTS_FILE).exists():
        try:
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading projects: {e}")
            return {}
    return {}

def save_projects(projects: dict) -> bool:
    try:
        with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(projects, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving projects: {e}")
        return False

PROJECTS = load_projects()


# ============ FUNCIONES PRINCIPALES ============
async def check_app_status(app_url: str) -> str:
    try:
        r = await http_client.get(app_url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            return "Online"
        else:
            return f"Unstable ({r.status_code})"
    except Exception:
        return "Down"

async def trigger_render_deploy(deploy_url: str) -> str:
    try:
        r = await http_client.post(deploy_url, timeout=DEPLOY_TIMEOUT)
        if r.status_code == 200 or r.status_code == 201:
            return "✅ Redeploy triggered"
        else:
            return f"❌ Deploy failed ({r.status_code})"
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}"

def build_status_page(project_names: list, statuses: dict) -> str:
    total = len(project_names)
    lines = []
    for idx, name in enumerate(project_names, start=1):
        status = statuses.get(name, "Unknown")
        emoji = "🟢" if status == "Online" else ("🟡" if status.startswith("Unstable") else "🔴")
        lines.append(f"{idx}. <b>{name}</b> — {emoji} {status}")
    
    return (
        f"📊 <b>Render Monitor</b>\n"
        f"🕒 Last check: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"⏱️ Interval: {CHECK_INTERVAL_MINUTES} min\n"
        f"📁 Projects: {total}\n\n"
        f"{chr(10).join(lines) if lines else 'No projects configured'}\n\n"
        f"📌 Page 1/{max(1, ceil(total / PAGE_SIZE))}"
    )

async def check_all_and_update_channel(send_notifications: bool = True) -> tuple:
    logger.info("🔍 Running periodic check...")
    
    project_names = list(PROJECTS.keys())
    statuses = {}
    redeploy_results = {}

    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])
        logger.info(f"  {name}: {statuses[name]}")

    for name, status in statuses.items():
        if status == "Down" and "deploy_url" in PROJECTS[name]:
            logger.warning(f"⚠️ {name} is Down - triggering redeploy...")
            result = await trigger_render_deploy(PROJECTS[name]["deploy_url"])
            redeploy_results[name] = result
            logger.warning(f"  → {result}")

    text = build_status_page(project_names, statuses)
    try:
        await app.edit_message_text(
            chat_id=STATUS_CHANNEL_ID,
            message_id=STATUS_MESSAGE_ID,
            text=text,
            parse_mode=ParseMode.HTML
        )
        logger.info("✅ Channel status updated")
    except Exception as e:
        logger.error(f"❌ Failed to update channel: {e}")

    if redeploy_results and send_notifications:
        msg = "🔄 <b>Auto-redeploy Summary</b>\n\n" + "\n".join([f"• {n}: {r}" for n, r in redeploy_results.items()])
        try:
            await app.send_message(OWNER_ID, msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"❌ Failed to notify owner: {e}")

    return statuses, redeploy_results


# ============ COMANDOS ============
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    logger.info(f"📨 Received /start from {message.from_user.id}")
    await message.reply(
        "🤖 <b>Render Monitor Bot</b>\n\n✅ <b>Bot funcionando correctamente</b>\n\n"
        "📊 <b>Comandos:</b>\n/status - Ver estado\n/check - Forzar verificación\n"
        "/redeploy [nombre] - Redeploy manual\n/add - Añadir proyecto\n"
        "/remove - Eliminar proyecto\n/projects - Listar proyectos\n"
        "/help - Ayuda detallada\n\n📢 <b>Canal:</b> @ecanarender"
    )

@app.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    await message.reply("🔍 Verificando estado...")
    project_names = list(PROJECTS.keys())
    statuses = {name: await check_app_status(PROJECTS[name]["app_url"]) for name in project_names}
    await message.reply(build_status_page(project_names, statuses), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("check") & filters.private)
async def check_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    msg = await message.reply("🔄 Forzando verificación...")
    _, redeploys = await check_all_and_update_channel(send_notifications=True)
    await msg.edit_text("✅ Verificación completada" + (" con redeploys" if redeploys else " - todo OK"))

@app.on_message(filters.command("projects") & filters.private)
async def list_projects_command(client: Client, message: Message):
    if not PROJECTS:
        await message.reply("📭 No hay proyectos configurados")
        return
    text = "<b>📋 PROYECTOS</b>\n\n" + "\n\n".join([
        f"<b>{idx}. {name}</b>\n📍 <code>{cfg['app_url'][:50]}...</code>\n🔄 {'✅' if 'deploy_url' in cfg else '❌'}"
        for idx, (name, cfg) in enumerate(PROJECTS.items(), 1)
    ]) + f"\n\n📌 Total: {len(PROJECTS)}"
    await message.reply(text, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("add") & filters.private)
async def add_project_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Uso: /add Nombre | URL | DeployHook")
        return
    parts = [p.strip() for p in args[1].split("|")]
    if len(parts) < 2:
        await message.reply("❌ Debes especificar nombre y URL")
        return
    name, app_url = parts[0], parts[1]
    deploy_url = parts[2] if len(parts) > 2 else None
    
    if not app_url.startswith(("http://", "https://")):
        await message.reply("❌ URL debe comenzar con http:// o https://")
        return
    if name in PROJECTS:
        await message.reply(f"❌ Ya existe '{name}'")
        return
    
    PROJECTS[name] = {"app_url": app_url}
    if deploy_url:
        PROJECTS[name]["deploy_url"] = deploy_url
    
    if save_projects(PROJECTS):
        await message.reply(f"✅ Proyecto <b>{name}</b> añadido", parse_mode=ParseMode.HTML)
        await check_all_and_update_channel(send_notifications=False)
    else:
        await message.reply("❌ Error al guardar")

@app.on_message(filters.command("remove") & filters.private)
async def remove_project_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Uso: /remove Nombre")
        return
    name = args[1].strip()
    if name not in PROJECTS:
        await message.reply(f"❌ No existe '{name}'")
        return
    del PROJECTS[name]
    if save_projects(PROJECTS):
        await message.reply(f"✅ Proyecto <b>{name}</b> eliminado", parse_mode=ParseMode.HTML)
        await check_all_and_update_channel(send_notifications=False)
    else:
        await message.reply("❌ Error al guardar")

@app.on_message(filters.command("redeploy") & filters.private)
async def redeploy_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(f"❌ Especifica un proyecto:\n{chr(10).join(PROJECTS.keys())}")
        return
    name = args[1].strip()
    if name not in PROJECTS:
        await message.reply(f"❌ Proyecto '{name}' no encontrado")
        return
    if "deploy_url" not in PROJECTS[name]:
        await message.reply(f"❌ '{name}' no tiene deploy hook")
        return
    msg = await message.reply(f"🔄 Redeployando {name}...")
    result = await trigger_render_deploy(PROJECTS[name]["deploy_url"])
    await msg.edit_text(f"📌 {name}: {result}")

@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await message.reply(
        "<b>📚 AYUDA</b>\n\n"
        "/add Nombre | URL | Hook - Añadir proyecto\n"
        "/remove Nombre - Eliminar proyecto\n"
        "/projects - Listar proyectos\n"
        "/status - Ver estado\n"
        "/check - Forzar verificación\n"
        "/redeploy Nombre - Redeploy manual\n"
        "/deployhook Nombre | URL - Configurar hook",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command("deployhook") & filters.private)
async def deployhook_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Uso: /deployhook Nombre | URL")
        return
    parts = [p.strip() for p in args[1].split("|")]
    if len(parts) < 2:
        await message.reply("❌ Formato: Nombre | URL")
        return
    name, deploy_url = parts[0], parts[1]
    if name not in PROJECTS:
        await message.reply(f"❌ No existe '{name}'")
        return
    if deploy_url.lower() == "none":
        if "deploy_url" in PROJECTS[name]:
            del PROJECTS[name]["deploy_url"]
            msg = f"✅ Deploy hook eliminado de <b>{name}</b>"
        else:
            msg = f"ℹ️ {name} no tenía deploy hook"
    else:
        if not deploy_url.startswith(("http://", "https://")):
            await message.reply("❌ URL debe comenzar con http:// o https://")
            return
        PROJECTS[name]["deploy_url"] = deploy_url
        msg = f"✅ Deploy hook configurado para <b>{name}</b>"
    if save_projects(PROJECTS):
        await message.reply(msg, parse_mode=ParseMode.HTML)
    else:
        await message.reply("❌ Error al guardar")


# ============ SCHEDULER Y MAIN ============
def start_scheduler(loop):
    scheduler = AsyncIOScheduler()
    async def run_check():
        await check_all_and_update_channel(send_notifications=True)
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(run_check(), loop),
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES)
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started - checking every {CHECK_INTERVAL_MINUTES} minutes")

async def main():
    logger.info("🚀 Starting bot...")
    await app.start()
    logger.info("🤖 Bot started successfully")
    logger.info(f"📁 Loaded {len(PROJECTS)} projects")
    
    start_scheduler(asyncio.get_running_loop())
    await check_all_and_update_channel(send_notifications=False)
    
    logger.info("📡 Bot is running and waiting for commands...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        asyncio.run(http_client.aclose())