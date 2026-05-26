import os
import io
import logging
import sys
from tempfile import NamedTemporaryFile

from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

# Configure logging to show everything
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Check for BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable is not set!")
    logger.error("Please add BOT_TOKEN in Render environment variables")
    sys.exit(1)
else:
    logger.info("✅ BOT_TOKEN found (first 10 chars: {})".format(BOT_TOKEN[:10]))

# Initialize Flask app
app = Flask(__name__)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Supported formats
SUPPORTED_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "BMP": "bmp"
}

# Conversation states
class ConvertStates(StatesGroup):
    waiting_for_format = State()

def get_format_keyboard():
    buttons = []
    for friendly_name, ext in SUPPORTED_FORMATS.items():
        buttons.append([InlineKeyboardButton(text=friendly_name, callback_data=f"format_{ext}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def start_command(message: types.Message):
    logger.info(f"Received /start from user {message.from_user.id}")
    await message.answer(
        "🖼️ *Image Converter Bot*\n\n"
        "Send me any image (JPG, PNG, WEBP, BMP) and I'll convert it to your preferred format.\n\n"
        "📌 *How to use:*\n"
        "1. Send me an image\n"
        "2. Choose the output format\n"
        "3. I'll send back the converted image\n\n"
        "Supported output formats: JPEG, PNG, WEBP, BMP",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "🔄 *How to convert an image:*\n"
        "1. Send any image (as a file or photo)\n"
        "2. Select the format you want from the buttons\n"
        "3. Wait a moment – I'll send the converted file\n\n"
        "⚙️ *Supported output formats:* JPEG, PNG, WEBP, BMP\n"
        "📁 Max file size: 20 MB\n\n"
        "Send /start to see the welcome message again.",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.photo or message.document)
async def handle_image(message: types.Message, state: FSMContext):
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            if not message.document.mime_type.startswith('image/'):
                await message.answer("❌ Please send an image file")
                return
            file_id = message.document.file_id

        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)

        await state.update_data(image_bytes=file_bytes.getvalue())
        await state.set_state(ConvertStates.waiting_for_format)

        await message.answer(
            "🎨 Choose the output format:",
            reply_markup=get_format_keyboard()
        )

    except Exception as e:
        logger.error(f"Error handling image: {e}")
        await message.answer("❌ Failed to process your image. Please try again.")

@dp.callback_query(ConvertStates.waiting_for_format)
async def process_format_selection(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Conversion cancelled.")
        await callback.answer()
        return

    format_ext = callback.data.replace("format_", "")
    user_data = await state.get_data()
    image_bytes = user_data.get("image_bytes")

    if not image_bytes:
        await callback.message.edit_text("❌ Session expired. Please send the image again.")
        await state.clear()
        await callback.answer()
        return

    await callback.message.edit_text(f"⏳ Converting to *{format_ext.upper()}*...", parse_mode="Markdown")
    await callback.answer()

    try:
        original = Image.open(io.BytesIO(image_bytes))

        if format_ext == "jpg" and original.mode in ("RGBA", "P"):
            rgb_image = Image.new("RGB", original.size, (255, 255, 255))
            rgb_image.paste(original, mask=original.split()[-1] if original.mode == "RGBA" else None)
            original = rgb_image

        with NamedTemporaryFile(suffix=f".{format_ext}", delete=False) as tmp:
            if format_ext == "jpg":
                original.save(tmp.name, "JPEG", quality=85)
            else:
                original.save(tmp.name, format_ext.upper())
            tmp_path = tmp.name

        with open(tmp_path, "rb") as output_file:
            await callback.message.answer_document(
                types.input_file.BufferedInputFile(output_file.read(), filename=f"converted.{format_ext}"),
                caption=f"✅ Converted to *{format_ext.upper()}*",
                parse_mode="Markdown"
            )

        os.unlink(tmp_path)
        await state.clear()
        await callback.message.delete()

    except Exception as e:
        logger.error(f"Conversion error: {e}")
        await callback.message.answer("❌ Conversion failed.")
        await state.clear()

async def run_bot():
    """Run the bot with proper error handling"""
    try:
        logger.info("🚀 Starting bot polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot polling failed: {e}")
        raise

# Flask health check endpoint (optional, for Render if needed)
@app.route('/')
@app.route('/health')
def health_check():
    return "Bot is running", 200

if __name__ == "__main__":
    import asyncio
    import threading
    
    # Run Flask in a separate thread (for health checks)
    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run the bot
    asyncio.run(run_bot())
