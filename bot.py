import asyncio
import sys
import threading
import os
import json
import logging
from datetime import datetime
from math import ceil
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from aiohttp import web

# ============ PATCH PARA PYTHON 3.14 ============
if sys.version_info >= (3, 14):
    print("🔧 Aplicando parche de compatibilidad para Python 3.14...")
    
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    import typing
    if not hasattr(typing.Union, '__module__'):
        typing.Union.__module__ = 'typing'
    
    if not hasattr(asyncio, 'get_event_loop'):
        asyncio.get_event_loop = asyncio.get_running_loop

# Cargar variables de entorno
load_dotenv()

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ CONFIGURACIÓN ============
# 🔐 TUS VARIABLES
API_ID = 14681595
API_HASH = "a86730aab5c59953c424abb4396d32d5"
BOT_TOKEN = "8728854601:AAFkSuFMdaNP0OWP5EYfLg9f-hgds-IQ0Pc"
OWNER_ID = 7970466590

# 📢 CANAL
STATUS_CHANNEL_ID = "@ecanarender"
STATUS_MESSAGE_ID = 2

# ⚙️ Configuración general
CHECK_INTERVAL_MINUTES = 60
PAGE_SIZE = 10
HTTP_TIMEOUT = 10
DEPLOY_TIMEOUT = 30
PROJECTS_FILE = "projects.json"

# Cliente HTTP asíncrono
http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

# Cliente de Pyrogram
app = Client(
    "render_manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============ SERVIDOR WEB PARA RENDER ============
async def health_check(request):
    """Endpoint para que Render verifique que el bot está vivo"""
    return web.Response(
        text="🤖 Render Monitor Bot is running!",
        content_type="text/html"
    )

async def status_page(request):
    """Página de estado simple"""
    projects_count = len(PROJECTS)
    html = f"""
    <html>
        <head><title>Render Monitor Bot</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h1>🤖 Render Monitor Bot</h1>
            <p>✅ Bot is running</p>
            <p>📁 Projects: {projects_count}</p>
            <p>⏱️ Check interval: {CHECK_INTERVAL_MINUTES} minutes</p>
            <p>📢 Channel: @ecanarender</p>
            <p><small>Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
        </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")

async def start_web_server():
    """Inicia servidor web en el puerto de Render"""
    port = int(os.environ.get("PORT", 10000))
    app_web = web.Application()
    app_web.router.add_get("/", health_check)
    app_web.router.add_get("/health", health_check)
    app_web.router.add_get("/status", status_page)
    
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"✅ Web server started on port {port}")
    logger.info(f"🌐 Status page: http://0.0.0.0:{port}/status")


# ============ GESTIÓN DE PROYECTOS ============

def load_projects() -> dict:
    """Carga los proyectos desde el archivo JSON"""
    if Path(PROJECTS_FILE).exists():
        try:
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading projects: {e}")
            return {}
    return {}


def save_projects(projects: dict) -> bool:
    """Guarda los proyectos en el archivo JSON"""
    try:
        with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(projects, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving projects: {e}")
        return False


# Cargar proyectos al inicio
PROJECTS = load_projects()


# ============ FUNCIONES PRINCIPALES ============

async def check_app_status(app_url: str) -> str:
    """Verifica el estado de una aplicación"""
    try:
        r = await http_client.get(app_url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            return "Online"
        else:
            return f"Unstable ({r.status_code})"
    except Exception as e:
        logger.debug(f"Error checking {app_url}: {e}")
        return "Down"


async def trigger_render_deploy(deploy_url: str) -> str:
    """Activa un redeploy en Render"""
    try:
        r = await http_client.post(deploy_url, timeout=DEPLOY_TIMEOUT)
        if r.status_code == 200 or r.status_code == 201:
            return "✅ Redeploy triggered"
        else:
            return f"❌ Deploy failed ({r.status_code})"
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}"


def build_status_page(project_names: list, statuses: dict) -> str:
    """Construye la página de estado"""
    total = len(project_names)
    pages = max(1, ceil(total / PAGE_SIZE))
    lines = []

    for idx, name in enumerate(project_names, start=1):
        status = statuses.get(name, "Unknown")
        
        if status == "Online":
            emoji = "🟢"
        elif status.startswith("Unstable"):
            emoji = "🟡"
        else:
            emoji = "🔴"
        
        lines.append(f"{idx}. <b>{name}</b> — {emoji} {status}")

    header = (
        f"📊 <b>Render Monitor</b>\n"
        f"🕒 Last check: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"⏱️ Interval: {CHECK_INTERVAL_MINUTES} min\n"
        f"📁 Projects: {total}\n\n"
    )
    
    body = "\n".join(lines) if lines else "No projects configured"
    footer = f"\n\n📌 Page 1/{pages}"
    
    return header + body + footer


async def check_all_and_update_channel(send_notifications: bool = True) -> tuple:
    """Verifica todos los proyectos y actualiza el canal"""
    logger.info("🔍 Running periodic check...")
    
    project_names = list(PROJECTS.keys())
    statuses = {}
    redeploy_results = {}

    # Verificar estado
    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])
        logger.info(f"  {name}: {statuses[name]}")

    # Auto redeploy
    for name, status in statuses.items():
        if status == "Down" and "deploy_url" in PROJECTS[name]:
            logger.warning(f"⚠️ {name} is Down - triggering redeploy...")
            result = await trigger_render_deploy(PROJECTS[name]["deploy_url"])
            redeploy_results[name] = result
            logger.warning(f"  → {result}")

    # Actualizar canal
    text = build_status_page(project_names, statuses)
    try:
        await app.edit_message_text(
            chat_id=STATUS_CHANNEL_ID,
            message_id=STATUS_MESSAGE_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logger.info("✅ Channel status updated")
    except Exception as e:
        logger.error(f"❌ Failed to update channel: {e}")

    # Notificar al admin
    if redeploy_results and send_notifications:
        msg = "🔄 <b>Auto-redeploy Summary</b>\n\n"
        for name, result in redeploy_results.items():
            msg += f"• {name}: {result}\n"
        try:
            await app.send_message(OWNER_ID, msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"❌ Failed to notify owner: {e}")

    return statuses, redeploy_results


# ============ COMANDOS ============

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Comando /start"""
    logger.info(f"📨 Received /start from {message.from_user.id}")
    await message.reply(
        "🤖 <b>Render Monitor Bot</b>\n\n"
        "✅ <b>Bot funcionando correctamente</b>\n\n"
        "<b>COMANDOS DISPONIBLES:</b>\n\n"
        "📊 <b>Monitoreo:</b>\n"
        "/status - Ver estado actual\n"
        "/check - Forzar verificación\n"
        "/redeploy [nombre] - Redeploy manual\n\n"
        "📝 <b>Gestión:</b>\n"
        "/add - Añadir proyecto\n"
        "/remove - Eliminar proyecto\n"
        "/edit - Editar proyecto\n"
        "/projects - Listar proyectos\n"
        "/deployhook - Configurar deploy hook\n\n"
        "❓ /help - Ayuda detallada\n\n"
        f"📢 <b>Canal de estado:</b> @ecanarender"
    )


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Comando /help"""
    await message.reply(
        "<b>📚 AYUDA DETALLADA</b>\n\n"
        
        "<b>📊 COMANDOS DE MONITOREO</b>\n"
        "• /status - Muestra el estado actual\n"
        "• /check - Fuerza verificación inmediata\n"
        "• /redeploy [nombre] - Redeploy manual\n\n"
        
        "<b>📝 COMANDOS DE GESTIÓN</b>\n"
        "• /add Nombre | URL | DeployHook\n"
        "  Ej: <code>/add MiApp | https://miapp.onrender.com | https://api.render.com/deploy/...</code>\n\n"
        
        "• /remove Nombre\n"
        "  Ej: <code>/remove MiApp</code>\n\n"
        
        "• /edit Nombre | NuevoNombre | NuevaURL | NuevoHook\n"
        "  Ej: <code>/edit MiApp | - | https://nueva-url.com | -</code>\n\n"
        
        "• /projects - Lista todos los proyectos\n"
        "• /deployhook Nombre | URL - Configurar deploy hook\n\n"
        
        "<b>⚙️ AUTO-REDEPLOY</b>\n"
        "El bot redeploya automáticamente proyectos 'Down'\n\n"
        
        f"📢 <b>Canal de estado:</b> @ecanarender\n"
        f"⏱️ <b>Intervalo:</b> {CHECK_INTERVAL_MINUTES} minutos",
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    """Comando /status"""
    await message.reply("🔍 Verificando estado...")
    
    project_names = list(PROJECTS.keys())
    statuses = {}
    
    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])
    
    text = build_status_page(project_names, statuses)
    await message.reply(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("check") & filters.private)
async def check_command(client: Client, message: Message):
    """Comando /check"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    msg = await message.reply("🔄 Forzando verificación...")
    statuses, redeploys = await check_all_and_update_channel(send_notifications=True)
    
    result = "✅ Verificación completada" + (" con redeploys" if redeploys else " - todo OK")
    await msg.edit_text(result)


@app.on_message(filters.command("projects") & filters.private)
async def list_projects_command(client: Client, message: Message):
    """Comando /projects"""
    if not PROJECTS:
        await message.reply("📭 No hay proyectos configurados")
        return
    
    text = "<b>📋 PROYECTOS CONFIGURADOS</b>\n\n"
    
    for idx, (name, config) in enumerate(PROJECTS.items(), 1):
        has_deploy = "✅" if "deploy_url" in config else "❌"
        text += f"<b>{idx}. {name}</b>\n"
        text += f"   📍 URL: <code>{config['app_url'][:50]}...</code>\n"
        text += f"   🔄 Deploy Hook: {has_deploy}\n\n"
    
    text += f"📌 Total: {len(PROJECTS)} proyectos"
    await message.reply(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("add") & filters.private)
async def add_project_command(client: Client, message: Message):
    """Comando /add"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "❌ Uso: <code>/add Nombre | URL | DeployHook</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    parts = [p.strip() for p in args[1].split("|")]
    if len(parts) < 2:
        await message.reply("❌ Debes especificar al menos nombre y URL")
        return
    
    name = parts[0]
    app_url = parts[1]
    deploy_url = parts[2] if len(parts) > 2 else None
    
    if not app_url.startswith(("http://", "https://")):
        await message.reply("❌ La URL debe comenzar con http:// o https://")
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
    """Comando /remove"""
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
    """Comando /redeploy"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        projects_list = "\n".join([f"• {name}" for name in PROJECTS.keys()])
        await message.reply(f"❌ Especifica un proyecto:\n\n{projects_list}")
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


@app.on_message(filters.command("deployhook") & filters.private)
async def deployhook_command(client: Client, message: Message):
    """Comando /deployhook"""
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
    
    name = parts[0]
    deploy_url = parts[1]
    
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


@app.on_message(filters.command("edit") & filters.private)
async def edit_project_command(client: Client, message: Message):
    """Comando /edit"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "❌ Uso: <code>/edit Nombre | NuevoNombre | NuevaURL | NuevoHook</code>\n"
            "Usa '-' para mantener valor actual",
            parse_mode=ParseMode.HTML
        )
        return
    
    parts = [p.strip() for p in args[1].split("|")]
    if len(parts) < 2:
        await message.reply("❌ Formato incorrecto")
        return
    
    old_name = parts[0]
    if old_name not in PROJECTS:
        await message.reply(f"❌ No existe '{old_name}'")
        return
    
    new_name = parts[1] if len(parts) > 1 and parts[1] != "-" else old_name
    new_url = parts[2] if len(parts) > 2 and parts[2] != "-" else PROJECTS[old_name]["app_url"]
    new_deploy = parts[3] if len(parts) > 3 and parts[3] != "-" else PROJECTS[old_name].get("deploy_url", "")
    
    if new_url and not new_url.startswith(("http://", "https://")):
        await message.reply("❌ La URL debe comenzar con http:// o https://")
        return
    
    new_project = {"app_url": new_url}
    if new_deploy:
        new_project["deploy_url"] = new_deploy
    
    if old_name != new_name:
        del PROJECTS[old_name]
        PROJECTS[new_name] = new_project
    else:
        PROJECTS[old_name] = new_project
    
    if save_projects(PROJECTS):
        await message.reply("✅ Proyecto actualizado", parse_mode=ParseMode.HTML)
        await check_all_and_update_channel(send_notifications=False)
    else:
        await message.reply("❌ Error al guardar")


# ============ SCHEDULER Y MAIN ============

def start_scheduler(loop):
    """Inicia el scheduler"""
    scheduler = AsyncIOScheduler()
    
    async def run_periodic_check():
        await check_all_and_update_channel(send_notifications=True)
    
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(run_periodic_check(), loop),
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
        id="auto_check_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started - checking every {CHECK_INTERVAL_MINUTES} minutes")


async def main():
    """Función principal"""
    logger.info("🚀 Starting bot...")
    
    # Iniciar servidor web (para Render)
    await start_web_server()
    
    await app.start()
    logger.info("🤖 Bot started successfully")
    logger.info(f"📁 Loaded {len(PROJECTS)} projects from {PROJECTS_FILE}")
    logger.info(f"📢 Status channel: @ecanarender (ID: {STATUS_CHANNEL_ID})")
    
    loop = asyncio.get_running_loop()
    start_scheduler(loop)
    
    # Primera verificación
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