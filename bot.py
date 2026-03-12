import os
import asyncio
import logging
from datetime import datetime
from math import ceil

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from projects import PROJECTS

# Cargar variables de entorno
load_dotenv()

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 🔐 TUS VARIABLES ORIGINALES
API_ID = 14681595
API_HASH = "a86730aab5c59953c424abb4396d32d5"
BOT_TOKEN = "8728854601:AAFkSuFMdaNP0OWP5EYfLg9f-hgds-IQ0Pc"
OWNER_ID = 7970466590
STATUS_CHANNEL_ID = -1003799101536
STATUS_MESSAGE_ID = 2

# Configuración
CHECK_INTERVAL_MINUTES = 60  # Puedes cambiarlo aquí o en .env
PAGE_SIZE = 10
HTTP_TIMEOUT = 10
DEPLOY_TIMEOUT = 30

# Cliente HTTP asíncrono
http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

# Cliente de Pyrogram
app = Client(
    "render_manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


async def check_app_status(app_url: str) -> str:
    """
    Verifica el estado de una aplicación haciendo una petición HTTP
    """
    try:
        r = await http_client.get(app_url, follow_redirects=True)
        if r.status_code == 200:
            return "Online"
        else:
            return f"Unstable ({r.status_code})"
    except Exception as e:
        logger.debug(f"Error checking {app_url}: {e}")
        return "Down"


async def trigger_render_deploy(deploy_url: str) -> str:
    """
    Activa un redeploy en Render usando el deploy hook
    """
    try:
        r = await http_client.post(deploy_url, timeout=DEPLOY_TIMEOUT)
        if r.status_code == 200 or r.status_code == 201:
            return "✅ Redeploy triggered"
        else:
            return f"❌ Deploy failed ({r.status_code})"
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}"


def build_status_page(project_names: list, statuses: dict) -> str:
    """
    Construye la página de estado con formato HTML
    """
    total = len(project_names)
    pages = max(1, ceil(total / PAGE_SIZE))
    lines = []

    for idx, name in enumerate(project_names, start=1):
        status = statuses.get(name, "Unknown")
        
        # Emoji según estado
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
        f"⏱️ Interval: {CHECK_INTERVAL_MINUTES} min\n\n"
    )
    
    body = "\n".join(lines) if lines else "No projects configured"
    footer = f"\n\n📌 Total: {total} projects | Page 1/{pages}"
    
    return header + body + footer


async def check_all_and_update_channel(send_notifications: bool = True) -> tuple:
    """
    Verifica todos los proyectos y actualiza el canal
    """
    logger.info("🔍 Running periodic check...")
    
    project_names = list(PROJECTS.keys())
    statuses = {}
    redeploy_results = {}

    # Verificar estado de cada proyecto
    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])
        logger.info(f"  {name}: {statuses[name]}")

    # Auto redeploy si está Down
    for name, status in statuses.items():
        if status == "Down" and "deploy_url" in PROJECTS[name]:
            logger.warning(f"⚠️ {name} is Down - triggering redeploy...")
            result = await trigger_render_deploy(PROJECTS[name]["deploy_url"])
            redeploy_results[name] = result
            logger.warning(f"  → {result}")

    # Actualizar mensaje en el canal
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

    # Notificar al owner si hubo redeploys
    if redeploy_results and send_notifications:
        msg = "🔄 <b>Auto-redeploy Summary</b>\n\n"
        for name, result in redeploy_results.items():
            msg += f"• {name}: {result}\n"
        try:
            await app.send_message(OWNER_ID, msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"❌ Failed to notify owner: {e}")

    return statuses, redeploy_results


# Comandos del bot
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Comando /start"""
    await message.reply(
        "🤖 <b>Render Monitor Bot</b>\n\n"
        "Comandos disponibles:\n"
        "/status - Ver estado actual\n"
        "/check - Forzar verificación ahora\n"
        "/redeploy [nombre] - Redeploy manual\n"
        "/help - Ayuda detallada"
    )


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Comando /help"""
    help_text = (
        "<b>📚 Ayuda del Bot</b>\n\n"
        "<b>Comandos:</b>\n"
        "• /status - Muestra el estado actual de todos los proyectos\n"
        "• /check - Fuerza una verificación inmediata\n"
        "• /redeploy [nombre] - Redeploy manual de un proyecto\n"
        "• /list - Lista todos los proyectos configurados\n\n"
        "<b>Auto-redeploy:</b>\n"
        "El bot redeploya automáticamente cualquier proyecto que detecte como 'Down'\n\n"
        f"⏱️ <b>Intervalo de verificación:</b> {CHECK_INTERVAL_MINUTES} minutos"
    )
    await message.reply(help_text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    """Comando /status - Muestra estado actual"""
    await message.reply("🔍 Verificando estado...")
    
    project_names = list(PROJECTS.keys())
    statuses = {}
    
    for name in project_names:
        statuses[name] = await check_app_status(PROJECTS[name]["app_url"])
    
    text = build_status_page(project_names, statuses)
    await message.reply(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("check") & filters.private)
async def check_command(client: Client, message: Message):
    """Comando /check - Fuerza verificación manual"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    msg = await message.reply("🔄 Forzando verificación...")
    statuses, redeploys = await check_all_and_update_channel(send_notifications=True)
    
    if redeploys:
        result = "✅ Verificación completada con redeploys"
    else:
        result = "✅ Verificación completada - todo OK"
    
    await msg.edit_text(result)


@app.on_message(filters.command("redeploy") & filters.private)
async def redeploy_command(client: Client, message: Message):
    """Comando /redeploy - Redeploy manual"""
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ No autorizado")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        projects_list = "\n".join([f"• {name}" for name in PROJECTS.keys()])
        await message.reply(
            f"❌ Especifica un proyecto:\n\n{projects_list}\n\n"
            f"Ejemplo: <code>/redeploy MiApp</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    project_name = args[1].strip()
    
    if project_name not in PROJECTS:
        await message.reply(f"❌ Proyecto '{project_name}' no encontrado")
        return
    
    if "deploy_url" not in PROJECTS[project_name]:
        await message.reply(f"❌ El proyecto '{project_name}' no tiene deploy hook configurado")
        return
    
    msg = await message.reply(f"🔄 Redeployando {project_name}...")
    result = await trigger_render_deploy(PROJECTS[project_name]["deploy_url"])
    await msg.edit_text(f"📌 {project_name}: {result}")


@app.on_message(filters.command("list") & filters.private)
async def list_command(client: Client, message: Message):
    """Comando /list - Lista proyectos"""
    if not PROJECTS:
        await message.reply("📭 No hay proyectos configurados")
        return
    
    text = "<b>📋 Proyectos configurados:</b>\n\n"
    for name, config in PROJECTS.items():
        has_deploy = "✅" if "deploy_url" in config else "❌"
        text += f"• <b>{name}</b>\n"
        text += f"  URL: <code>{config['app_url'][:50]}...</code>\n"
        text += f"  Auto-deploy: {has_deploy}\n\n"
    
    await message.reply(text, parse_mode=ParseMode.HTML)


def start_scheduler(loop):
    """Inicia el scheduler para verificaciones periódicas"""
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
    await app.start()
    logger.info("🤖 Bot started successfully")
    
    # Iniciar scheduler
    loop = asyncio.get_running_loop()
    start_scheduler(loop)
    
    # Primera verificación
    await check_all_and_update_channel(send_notifications=False)
    
    # Mantener el bot corriendo
    logger.info("📡 Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        # Limpiar recursos
        asyncio.run(http_client.aclose())