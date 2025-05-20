import logging
import os
import subprocess
import uuid
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# Конфигурация из переменных окружения
TOKEN = os.getenv('BOT_TOKEN')
TEMP_FOLDER = './temp'
ALLOWED_USERS = set(map(int, os.getenv('ALLOWED_USER_IDS', '').split(',')))

logging.basicConfig(level=logging.INFO)

# Создаём временную папку, если её нет
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Определение cookie-файла по URL
def get_cookie_file(url: str) -> str:
    if 'instagram.com' in url:
        return './cookie_instagram.txt'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return './cookie_youtube.txt'
    return ''

# Функция скачивания и отправки видео
async def download_and_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text('⛔️ У вас нет доступа к этому боту.')
        logging.warning(f"Доступ запрещён для user_id: {user_id}")
        return

    url = update.message.text
    msg = await update.message.reply_text('⏳ Скачиваю видео...')

    unique_id = str(uuid.uuid4())
    temp_file = f'{TEMP_FOLDER}/{unique_id}.mp4'
    cookie_file = get_cookie_file(url)

    # Формируем команду yt-dlp
    command = ['yt-dlp']
    if cookie_file:
        command += ['--cookies', cookie_file]
    command += [
        '-f', 'mp4[filesize<50M]/bv*+ba/b[filesize<50M]',
        '--no-playlist',
        '--max-filesize', '50M',
        '-o', temp_file,
        url
    ]

    logging.info(f"Запуск команды yt-dlp: {' '.join(command)}")

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        logging.info(f"Завершено. stdout: {result.stdout.decode('utf-8')}")

        if not os.path.exists(temp_file):
            await msg.edit_text('❌ Видео не было загружено. Возможно, оно превышает лимит или недоступно.')
            return

        logging.info(f"Видео скачано: {temp_file}")
        await msg.edit_text('📤 Отправляю видео...')

        file_size = os.path.getsize(temp_file)
        if file_size > 50 * 1024 * 1024:
            await msg.edit_text('❌ Видео слишком большое для отправки в Telegram (>50MB).')
            logging.warning(f"Файл слишком большой: {file_size} байт")
        else:
            with open(temp_file, 'rb') as video:
                await update.message.reply_video(video)

        await msg.delete()

    except subprocess.TimeoutExpired:
        logging.error("Превышено время ожидания скачивания видео")
        await msg.edit_text('❌ Превышено время ожидания скачивания видео.')
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
    if not TOKEN or not ALLOWED_USERS:
        raise ValueError("Переменные окружения BOT_TOKEN и ALLOWED_USER_IDS обязательны для запуска")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_and_send_video))

    logging.info('Бот запущен...')
    app.run_polling()
