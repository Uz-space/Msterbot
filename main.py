"""
No-Code Bot Deployer — Master Bot
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("deployer")

# ---------------------------------------------------------------------------
# Konfiguratsiya  — faqat shu qatorni o'zgartiring
# ---------------------------------------------------------------------------

MASTER_TOKEN: str = "8656657889:AAEr6APfPm3Ah7VeTlqyhTYNvVsN9BqLYPg"
BOTS_ROOT: Path   = Path("/app/user_bots")
PYTHON_BIN: str   = sys.executable

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Form(StatesGroup):
    waiting_token = State()

# ---------------------------------------------------------------------------
# Yordamchi
# ---------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"[^\w.\-]")

def sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = _SAFE_NAME.sub("_", name)
    return name[:128] or "unnamed"

def user_dir(user_id: int) -> Path:
    d = BOTS_ROOT / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

def deploy_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Boshlash 🚀", callback_data="deploy")]
    ])

def validate(uid: int) -> tuple[bool, str]:
    d = user_dir(uid)
    files = {f.name for f in d.iterdir() if f.is_file()}

    if "main.py" not in files:
        return False, "⚠️ *main.py* fayli topilmadi. Yuboring."

    env_path = d / ".env"
    if not env_path.exists():
        return False, "⚠️ *.env* fayli topilmadi. Yuboring."

    text = env_path.read_text(errors="replace")
    for line in text.splitlines():
        if line.strip().startswith("BOT_TOKEN"):
            parts = line.split("=", 1)
            if len(parts) == 2 and parts[1].strip():
                return True, ""
    return False, "⚠️ *.env* ichida `BOT_TOKEN` bo'sh. Tokenni yuboring."

def deploy_bot(uid: int) -> subprocess.Popen:
    d = user_dir(uid)
    proc = subprocess.Popen(
        [PYTHON_BIN, "main.py"],
        cwd=d,
        stdout=open(d / "stdout.log", "a"),
        stderr=open(d / "stderr.log", "a"),
        start_new_session=True,
    )
    log.info("Deploy | user=%s | PID=%s", uid, proc.pid)
    return proc

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

bot = Bot(token=MASTER_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ---------------------------------------------------------------------------
# Handlerlar
# ---------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer(
        "Salom! 👋\n\n"
        "Avval foydalanuvchi botingizning *tokenini* yuboring:\n"
        "_(BotFather dan olgan token)_",
        parse_mode="Markdown",
    )
    await state.set_state(Form.waiting_token)


@dp.message(Form.waiting_token)
async def receive_token(msg: Message, state: FSMContext) -> None:
    token = msg.text.strip() if msg.text else ""

    if not token or ":" not in token:
        await msg.answer("❌ Token noto'g'ri ko'rinadi. Qaytadan yuboring:")
        return

    # .env faylga yozamiz
    env_path = user_dir(msg.from_user.id) / ".env"
    env_path.write_text(f"BOT_TOKEN={token}\n")
    log.info("Token saqlandi | user=%s", msg.from_user.id)

    await state.clear()
    await msg.answer(
        "✅ Token saqlandi!\n\n"
        "Endi bot fayllaringizni yuboring (`main.py`, `handlers.py` va h.k.).\n"
        "Hammasi tayyor bo'lgach *Boshlash 🚀* tugmasini bosing.",
        parse_mode="Markdown",
    )


@dp.message(F.document)
async def receive_file(msg: Message) -> None:
    doc  = msg.document
    safe = sanitize_filename(doc.file_name or "file")
    dest = user_dir(msg.from_user.id) / safe

    file = await bot.get_file(doc.file_id)
    await bot.download_file(file.file_path, destination=dest)
    log.info("Fayl saqlandi | user=%s | %s", msg.from_user.id, safe)

    await msg.answer(
        f"✅ *{safe}* saqlandi.\n\nYana fayl bormi?",
        parse_mode="Markdown",
        reply_markup=deploy_btn(),
    )


@dp.callback_query(F.data == "deploy")
async def cb_deploy(call: CallbackQuery) -> None:
    uid = call.from_user.id
    await call.answer()

    ok, err = validate(uid)
    if not ok:
        await call.message.answer(err, parse_mode="Markdown")
        return

    await call.message.answer("⏳ Botingiz ishga tushirilmoqda...")

    try:
        proc = deploy_bot(uid)
    except Exception as exc:
        log.exception("Deploy xatosi | user=%s", uid)
        await call.message.answer(f"❌ Xato:\n`{exc}`", parse_mode="Markdown")
        return

    await call.message.answer(
        f"🔥🚀 *Hamma narsa mukammal!*\n\n"
        f"Botingiz serverda jonli ishga tushirildi!\n_(PID: `{proc.pid}`)_",
        parse_mode="Markdown",
    )

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    log.info("Master bot ishga tushmoqda...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
