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


def deploy_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Boshlash 🚀", callback_data="deploy")]
    ])


def extract_token_from_file(path: Path) -> str | None:
    """Fayl ichidan BOT_TOKEN qiymatini qidiradi."""
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return None

    # .env uslubi: BOT_TOKEN=1234:ABC
    for line in text.splitlines():
        line = line.strip()
        if "BOT_TOKEN" in line and "=" in line:
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if _TOKEN_RE.fullmatch(val):
                return val

    # Python uslubi: TOKEN = "1234:ABC" yoki os.environ["1234:ABC"]
    match = _TOKEN_RE.search(text)
    if match:
        return match.group()

    return None


def fix_env(uid: int, token: str) -> None:
    """Foydalanuvchi papkasidagi .env ga BOT_TOKEN yozadi."""
    env_path = user_dir(uid) / ".env"
    env_path.write_text(f"BOT_TOKEN={token}\n")
    log.info("Token .env ga yozildi | user=%s", uid)


def scan_and_fix(uid: int) -> tuple[bool, str, str]:
    """
    Papkani skanerlaydi.
    Qaytaradi: (ok, xato_xabari, topilgan_token)
    """
    d = user_dir(uid)
    files = list(d.iterdir())

    if not any(f.name == "main.py" for f in files if f.is_file()):
        return False, "⚠️ *main.py* topilmadi. Yuboring.", ""

    # Barcha fayllardan token qidirish
    token = ""
    for f in files:
        if f.is_file():
            found = extract_token_from_file(f)
            if found:
                token = found
                log.info("Token topildi | fayl=%s | user=%s", f.name, uid)
                break

    if not token:
        return False, (
            "⚠️ Hech bir faylda *BOT_TOKEN* topilmadi.\n\n"
            "Tokeningizni menga yuboring (matn sifatida)."
        ), ""

    return True, "", token


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
        "Bot fayllaringizni yuboring (`main.py`, va boshqalar).\n"
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
    """Foydalanuvchi tokenni matn sifatida yuborsa."""
    token = (msg.text or "").strip()
    if not _TOKEN_RE.fullmatch(token):
        await msg.answer(
            "❌ Token noto'g'ri. To'g'ri ko'rinish:\n`1234567890:ABCdef...`",
            parse_mode="Markdown",
        )
        return

    fix_env(msg.from_user.id, token)
    await state.clear()
    await msg.answer(
        "✅ Token saqlandi! Endi *Boshlash 🚀* tugmasini bosing.",
        parse_mode="Markdown",
        reply_markup=deploy_btn(),
    )


@dp.callback_query(F.data == "deploy")
async def cb_deploy(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    await call.answer()

    ok, err, token = scan_and_fix(uid)

    if not ok:
        # Token topilmadi — foydalanuvchidan so'raymiz
        await call.message.answer(err, parse_mode="Markdown")
        await state.set_state(Form.waiting_token)
        return

    # Token topildi — .env ga yozamiz
    fix_env(uid, token)

    await call.message.answer("⏳ Botingiz ishga tushirilmoqda...")

    try:
        proc = deploy_bot(uid)
    except Exception as exc:
        log.exception("Deploy xatosi | user=%s", uid)
        await call.message.answer(f"❌ Xato:\n`{exc}`", parse_mode="Markdown")
        return

    # 3 sekund kutib tekshiramiz
    await asyncio.sleep(3)
    if proc.poll() is not None:
        stderr_path = user_dir(uid) / "stderr.log"
        stderr = ""
        if stderr_path.exists():
            stderr = stderr_path.read_text(errors="replace").strip()[-800:]
        await call.message.answer(
            f"❌ Bot ishga tushmadi\\.\n\n"
            f"*Xato:*\n```\n{stderr or 'stderr.log bosh'}\n```",
            parse_mode="MarkdownV2",
        )
        return

    await call.message.answer(
        f"🔥🚀 *Hamma narsa mukammal!*\n\n"
        f"Botingiz serverda jonli ishga tushirildi\\!\n_PID: `{proc.pid}`_",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    log.info("Master bot ishga tushmoqda...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
