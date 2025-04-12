import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
import subprocess
import os
import uuid

# Конфигурация
TOKEN = ''
TEMP_FOLDER = './temp'
COOKIE_FILE = './cookie.txt'

logging.basicConfig(level=logging.INFO)

# Создаём временную папку, если её нет
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Функция скачивания и отправки видео
async def download_and_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    msg = await update.message.reply_text('⏳ Скачиваю видео...')

    unique_id = str(uuid.uuid4())
    temp_file = f'{TEMP_FOLDER}/{unique_id}.mp4'

    # Используем yt-dlp с cookie для скачивания и ffmpeg для конвертации
    command = [
        'yt-dlp',
        '--cookies', COOKIE_FILE,
        '-f', 'mp4',
        '-o', temp_file,
        url
    ]

    logging.info(f"Запуск команды yt-dlp: {' '.join(command)}")

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"Видео скачано: {temp_file}")

        await msg.edit_text('📤 Отправляю видео...')

        # Отправляем видео обратно пользователю
        with open(temp_file, 'rb') as video:
            await update.message.reply_video(video)

        await msg.delete()

    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка скачивания видео: {e.stderr.decode('utf-8')}")
        await msg.edit_text(f'❌ Ошибка скачивания видео:\n{e.stderr.decode("utf-8")}')
    except Exception as e:
        logging.exception("Непредвиденная ошибка")
        await msg.edit_text(f'❌ Возникла непредвиденная ошибка:\n{str(e)}')
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

# Точка входа
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_and_send_video))

    logging.info('Бот запущен...')
    app.run_polling()