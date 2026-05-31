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
# Yordamchi funksiyalar
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


def save_token(uid: int, token: str) -> None:
    """Tokenni .token fayliga saqlaydi."""
    (user_dir(uid) / ".token").write_text(token.strip())
    log.info("Token .token ga saqlandi | user=%s", uid)


def load_token(uid: int) -> str:
    """
    Tokenni quyidagi tartibda qidiradi:
    1. .token fayli
    2. Barcha fayllar ichidan regex bilan
    """
    tf = user_dir(uid) / ".token"
    if tf.exists():
        t = tf.read_text().strip()
        if _TOKEN_RE.fullmatch(t):
            log.info("Token .token dan olindi | user=%s", uid)
            return t

    # Barcha fayllardan qidirish
    d = user_dir(uid)
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        m = _TOKEN_RE.search(text)
        if m:
            found = m.group()
            log.info("Token fayldan topildi | fayl=%s | user=%s", f.name, uid)
            return found

    return ""


def deep_patch(uid: int, token: str) -> None:
    """
    Foydalanuvchi papkasidagi BARCHA .py va .env fayllarni ochib,
    ichidagi har qanday token ko'rinishini yangi token bilan almashtiradi.
    Quyidagi barcha variantlarni ushlaydi:
      - MASTER_TOKEN = "..."
      - BOT_TOKEN = "..."
      - TOKEN = "..."
      - os.environ["..."] / os.environ['...']
      - os.getenv("...") / os.getenv("...", "...")
      - Bot(token="...")
      - "1234567890:ABCxyz..." (to'g'ridan-to'g'ri token qiymati)
    """
    d = user_dir(uid)
    patched_files = []

    for f in d.iterdir():
        if not f.is_file():
            continue
        if f.suffix not in (".py", ".env", "") and f.name != ".env":
            continue

        try:
            original = f.read_text(errors="replace")
        except Exception:
            continue

        text = original

        # 1. Har qanday o'zgaruvchi = "token" yoki = 'token'
        text = re.sub(
            r'([A-Z_]*TOKEN[A-Z_]*\s*=\s*)["\'][^"\']{10,}["\']',
            lambda m: m.group(1) + f'"{token}"',
            text,
        )

        # 2. os.environ["KEY"] yoki os.environ['KEY']
        text = re.sub(
            r'os\.environ\[["\'][^"\']+["\']\]',
            f'"{token}"',
            text,
        )

        # 3. os.getenv("KEY") yoki os.getenv("KEY", "default")
        text = re.sub(
            r'os\.getenv\(["\'][^"\']+["\'](?:\s*,\s*["\'][^"\']*["\'])?\)',
            f'"{token}"',
            text,
        )

        # 4. Bot(token="...") ichidagi token
        text = re.sub(
            r'(Bot\s*\(\s*token\s*=\s*)["\'][^"\']{10,}["\']',
            lambda m: m.group(1) + f'"{token}"',
            text,
        )

        # 5. To'g'ridan-to'g'ri token qiymati qolgan bo'lsa
        text = re.sub(
            r'["\'](\d{8,12}:[A-Za-z0-9_-]{35,})["\']',
            f'"{token}"',
            text,
        )

        # .env fayli uchun BOT_TOKEN= qatorini yozamiz/almashtiramiz
        if f.name == ".env":
            if "BOT_TOKEN" in text:
                text = re.sub(r'BOT_TOKEN\s*=.*', f'BOT_TOKEN={token}', text)
            else:
                text = f"BOT_TOKEN={token}\n" + text

        if text != original:
            f.write_text(text)
            patched_files.append(f.name)

    # .env ni har doim yozamiz (yo'q bo'lsa ham)
    env_path = d / ".env"
    env_path.write_text(f"BOT_TOKEN={token}\n")

    log.info("Patch qilindi | user=%s | fayllar=%s", uid, patched_files)


def do_deploy(uid: int) -> subprocess.Popen:
    d = user_dir(uid)
    (d / "stderr.log").write_text("")
    (d / "stdout.log").write_text("")
    proc = subprocess.Popen(
        [PYTHON_BIN, "main.py"],
        cwd=d,
        stdout=open(d / "stdout.log", "a"),
        stderr=open(d / "stderr.log", "a"),
        start_new_session=True,
    )
    log.info("Deploy | user=%s | PID=%s", uid, proc.pid)
    return proc


def read_stderr(uid: int) -> str:
    p = user_dir(uid) / "stderr.log"
    if not p.exists():
        return "Log topilmadi"
    return p.read_text(errors="replace").strip()[-1500:]


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
            "❌ Token noto'g'ri formatda.\n"
            "To'g'ri ko'rinish: `1234567890:ABCdef...`",
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

    # 3. Barcha fayllarni chuqur patch qilish
    deep_patch(uid, token)

    await call.message.answer("⏳ Botingiz ishga tushirilmoqda...")

    try:
        proc = do_deploy(uid)
    except Exception as exc:
        log.exception("Deploy xatosi | user=%s", uid)
        await call.message.answer(
            f"❌ Ishga tushirishda xato:\n`{exc}`",
            parse_mode="Markdown",
        )
        return

    # 3 sekund kutib tekshiramiz
    await asyncio.sleep(3)

    if proc.poll() is not None:
        stderr = read_stderr(uid)
        await call.message.answer(
            f"❌ Bot ishga tushmadi.\n\n*Xato:*\n```\n{stderr}\n```",
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
