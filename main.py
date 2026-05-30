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
# Konfiguratsiya
# ---------------------------------------------------------------------------

BOT_TOKEN: str  = os.getenv("MASTER_BOT_TOKEN", "")
BOTS_ROOT: Path = Path(os.getenv("BOTS_ROOT", "/app/user_bots"))
PYTHON_BIN: str = os.getenv("PYTHON_BIN", sys.executable)

if not BOT_TOKEN:
    log.critical("MASTER_BOT_TOKEN environment variable topilmadi! To'ldiring.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
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


def _launch_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Boshlash 🚀", callback_data="deploy")]
        ]
    )


# ---------------------------------------------------------------------------
# Validatsiya
# ---------------------------------------------------------------------------

def validate_user_dir(uid: int) -> tuple[bool, str]:
    d = user_dir(uid)
    files = {f.name for f in d.iterdir() if f.is_file()}

    if "main.py" not in files:
        return False, (
            "⚠️ *main.py* fayli topilmadi.\n"
            "Iltimos, loyihangizdagi `main.py` ni yuboring."
        )

    if ".env" not in files:
        return False, (
            "⚠️ *.env* fayli topilmadi.\n"
            "Iltimos, `.env` faylini yuboring (ichida `BOT_TOKEN` bo'lishi shart)."
        )

    env_text = (d / ".env").read_text(errors="replace")
    if not _env_has_token(env_text):
        return False, (
            "⚠️ *.env* fayli ichida `BOT_TOKEN` qiymati bo'sh yoki topilmadi.\n"
            "Masalan: `BOT_TOKEN=1234567890:ABC...` ko'rinishida to'ldiring."
        )

    return True, ""


def _env_has_token(text: str) -> bool:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BOT_TOKEN"):
            parts = line.split("=", 1)
            if len(parts) == 2 and parts[1].strip():
                return True
    return False


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def deploy_bot(uid: int) -> subprocess.Popen:
    d = user_dir(uid)
    log.info("Deploy boshlandi | user=%s | dir=%s", uid, d)
    proc = subprocess.Popen(
        [PYTHON_BIN, "main.py"],
        cwd=d,
        stdout=open(d / "stdout.log", "a"),
        stderr=open(d / "stderr.log", "a"),
        start_new_session=True,
    )
    log.info("Deploy muvaffaqiyatli | user=%s | PID=%s", uid, proc.pid)
    return proc


# ---------------------------------------------------------------------------
# Bot va Handlerlar
# ---------------------------------------------------------------------------

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await msg.answer(
        "Salom! 👋\n\n"
        "Men *No-Code Bot Deployer* — siz menga bot fayllaringizni "
        "birma-bir yuboring (`main.py`, `.env`, handlers.py va h.k.), "
        "keyin *Boshlash 🚀* tugmasini bosing — botingiz serverda jonlanadi!\n\n"
        "_Birinchi faylni yuboring:_",
        parse_mode="Markdown",
    )


@dp.message(F.document)
async def receive_file(msg: Message) -> None:
    doc      = msg.document
    raw_name = doc.file_name or "file"
    safe     = sanitize_filename(raw_name)
    dest     = user_dir(msg.from_user.id) / safe

    file = await bot.get_file(doc.file_id)
    await bot.download_file(file.file_path, destination=dest)

    log.info("Fayl saqlandi | user=%s | fayl=%s", msg.from_user.id, safe)

    await msg.answer(
        f"✅ *{safe}* saqlandi.\n\nYana fayl bormi?",
        parse_mode="Markdown",
        reply_markup=_launch_btn(),
    )


@dp.callback_query(F.data == "deploy")
async def cb_deploy(call: CallbackQuery) -> None:
    uid = call.from_user.id
    await call.answer()

    ok, err_msg = validate_user_dir(uid)
    if not ok:
        await call.message.answer(err_msg, parse_mode="Markdown")
        return

    await call.message.answer("⏳ Botingiz ishga tushirilmoqda...")

    try:
        proc = deploy_bot(uid)
    except Exception as exc:
        log.exception("Deploy xatosi | user=%s", uid)
        await call.message.answer(
            f"❌ Texnik xato yuz berdi:\n`{exc}`",
            parse_mode="Markdown",
        )
        return

    await call.message.answer(
        f"🔥🚀 *Hamma narsa mukammal!*\n\n"
        f"Botingiz serverda jonli (live) ishga tushirildi!\n"
        f"_(PID: `{proc.pid}`)_",
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
