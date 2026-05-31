"""
No-Code Bot Deployer — Master Bot
"""

import asyncio
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("deployer")

# ---------------------------------------------------------------------------
# Konfiguratsiya
# ---------------------------------------------------------------------------

MASTER_TOKEN: str = "8656657889:AAEr6APfPm3Ah7VeTlqyhTYNvVsN9BqLYPg"
BOTS_ROOT: Path   = Path("/app/user_bots")
PYTHON_BIN: str   = sys.executable

_SAFE_NAME = re.compile(r"[^\w.\-]")
_TOKEN_RE  = re.compile(r"\d{8,12}:[A-Za-z0-9_-]{35,}")

# ---------------------------------------------------------------------------
# Yordamchi
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = _SAFE_NAME.sub("_", name)
    return name[:128] or "unnamed"


def user_dir(user_id: int) -> Path:
    d = BOTS_ROOT / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_file(uid: int) -> Path:
    """Token saqlanadigan maxsus fayl."""
    return user_dir(uid) / ".token"


def save_token(uid: int, token: str) -> None:
    token_file(uid).write_text(token.strip())
    log.info("Token saqlandi | user=%s", uid)


def load_token(uid: int) -> str:
    """Avval .token faylidan o'qiydi, topilmasa barcha fayllardan qidiradi."""
    tf = token_file(uid)
    if tf.exists():
        t = tf.read_text().strip()
        if _TOKEN_RE.fullmatch(t):
            return t

    # Fayllar ichidan qidirish
    d = user_dir(uid)
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.name.startswith(".token"):
            continue
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue

        for line in text.splitlines():
            stripped = line.strip()
            if "BOT_TOKEN" in stripped and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                if _TOKEN_RE.fullmatch(val):
                    return val

        m = _TOKEN_RE.search(text)
        if m:
            return m.group()

    return ""


def patch_main_py(uid: int, token: str) -> None:
    """main.py ichidagi barcha token joylarini to'g'ri token bilan almashtiradi."""
    main_path = user_dir(uid) / "main.py"
    if not main_path.exists():
        return
    text = main_path.read_text(errors="replace")

    # TOKEN_VAR = "..." yoki TOKEN_VAR = '...'
    text = re.sub(
        r'((?:MASTER_TOKEN|BOT_TOKEN|API_TOKEN|TOKEN)\s*=\s*)["\'][^"\']*["\']',
        rf'\g<1>"{token}"',
        text,
    )
    # os.environ["KEY"] yoki os.environ['KEY']
    text = re.sub(
        r'os\.environ\[["\'][^"\']*["\']\]',
        f'"{token}"',
        text,
    )
    # os.getenv("KEY") yoki os.getenv("KEY", "default")
    text = re.sub(
        r'os\.getenv\(["\'][^"\']*["\'](?:\s*,\s*["\'][^"\']*["\'])?\)',
        f'"{token}"',
        text,
    )

    main_path.write_text(text)
    log.info("main.py patch qilindi | user=%s", uid)


def write_env(uid: int, token: str) -> None:
    env_path = user_dir(uid) / ".env"
    env_path.write_text(f"BOT_TOKEN={token}\n")


def deploy_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Boshlash 🚀", callback_data="deploy")]
    ])


def do_deploy(uid: int) -> subprocess.Popen:
    d = user_dir(uid)
    (d / "stderr.log").write_text("")
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
# State
# ---------------------------------------------------------------------------

class Form(StatesGroup):
    waiting_token = State()


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
        "Bot fayllaringizni yuboring (`main.py` va boshqalar).\n"
        "Tayyor bo'lgach *Boshlash 🚀* tugmasini bosing.",
        parse_mode="Markdown",
    )


@dp.message(F.document)
async def receive_file(msg: Message, state: FSMContext) -> None:
    await state.clear()
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


@dp.message(Form.waiting_token)
async def receive_token_text(msg: Message, state: FSMContext) -> None:
    token = (msg.text or "").strip()
    if not _TOKEN_RE.fullmatch(token):
        await msg.answer(
            "❌ Token noto'g'ri formatda.\nTo'g'ri ko'rinish: `1234567890:ABCdef...`",
            parse_mode="Markdown",
        )
        return

    save_token(msg.from_user.id, token)
    await state.clear()
    await msg.answer(
        "✅ Token qabul qilindi! Endi *Boshlash 🚀* tugmasini bosing.",
        parse_mode="Markdown",
        reply_markup=deploy_btn(),
    )


@dp.callback_query(F.data == "deploy")
async def cb_deploy(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    await call.answer()

    # 1. main.py borligini tekshir
    if not (user_dir(uid) / "main.py").exists():
        await call.message.answer(
            "⚠️ *main.py* topilmadi. Yuboring.",
            parse_mode="Markdown",
        )
        return

    # 2. Token yuklash
    token = load_token(uid)
    if not token:
        await call.message.answer(
            "⚠️ Token topilmadi.\n\nBotingiz tokenini yuboring:",
            parse_mode="Markdown",
        )
        await state.set_state(Form.waiting_token)
        return

    # 3. main.py patch + .env yozish
    patch_main_py(uid, token)
    write_env(uid, token)

    await call.message.answer("⏳ Botingiz ishga tushirilmoqda...")

    try:
        proc = do_deploy(uid)
    except Exception as exc:
        log.exception("Deploy xatosi | user=%s", uid)
        await call.message.answer(f"❌ Xato:\n`{exc}`", parse_mode="Markdown")
        return

    await asyncio.sleep(3)

    if proc.poll() is not None:
        stderr_path = user_dir(uid) / "stderr.log"
        stderr = ""
        if stderr_path.exists():
            stderr = stderr_path.read_text(errors="replace").strip()[-1000:]
        await call.message.answer(
            f"❌ Bot ishga tushmadi.\n\n*Xato:*\n```\n{stderr or 'Noma\\'lum xato'}\n```",
            parse_mode="Markdown",
        )
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
