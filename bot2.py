import logging
import re
import select
import os
import subprocess
import uuid
import time
import random
from datetime import date
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters, CommandHandler

# Конфигурация из переменных окружения
TOKEN = os.getenv('BOT_TOKEN')
TEMP_FOLDER = './temp'

# Безопасный парсер ALLOWED_USER_IDS (запятая-разделитель, игнор пустых/ошибочных значений)
def parse_allowed_users(env_value: str) -> set[int]:
    users = set()
    if not env_value:
        return users
    for part in env_value.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            users.add(int(part))
        except ValueError:
            logging.warning(f"Пропускаю некорректный user id: {part}")
    return users

ALLOWED_USERS = parse_allowed_users(os.getenv('ALLOWED_USER_IDS', ''))

# Памятная статистика за время работы процесса (сбрасывается при перезапуске)
TOTAL_SUCCESS = 0
TOTAL_FAIL = 0

logging.basicConfig(level=logging.INFO)
# Убираем шумные логи HTTP-запросов Telegram (httpx)
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)
httpx_logger.disabled = True

# Создаём временную папку, если её нет
os.makedirs(TEMP_FOLDER, exist_ok=True)

def increment_success() -> None:
    global TOTAL_SUCCESS
    TOTAL_SUCCESS += 1

def increment_fail() -> None:
    global TOTAL_FAIL
    TOTAL_FAIL += 1

def get_stats_text() -> str:
    return f"успехов: {TOTAL_SUCCESS}, ошибок: {TOTAL_FAIL}"

def build_status(stage: str, attempt: int | None = None, max_attempts: int | None = None, progress: str | None = None) -> str:
    parts = [stage]
    if attempt and max_attempts:
        parts.append(f"(попытка {attempt}/{max_attempts})")
    if progress:
        parts.append(progress)
    parts.append(f"— {get_stats_text()}")
    return ' '.join(parts)

# Определение cookie-файла по URL
def get_cookie_file(url: str) -> str:
    if 'instagram.com' in url:
        return './cookie_instagram.txt'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return './cookie_youtube.txt'
    return ''

# Функция перекодирования видео под лимит Telegram
def compress_video(input_path: str, output_path: str) -> bool:
    try:
        command = [
            'ffmpeg', '-i', input_path,
            '-vf', 'scale=w=640:h=-2',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '28',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return os.path.exists(output_path) and os.path.getsize(output_path) <= 50 * 1024 * 1024
    except Exception as e:
        logging.error(f"Ошибка перекодирования видео: {e}")
        return False

# Функция скачивания и отправки видео
async def download_and_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text('⛔️ У вас нет доступа к этому боту.')
        logging.warning(f"Доступ запрещён для user_id: {user_id}")
        return

    url = update.message.text
    msg = await update.message.reply_text(build_status('⏳ Скачиваю видео...'))

    unique_id = str(uuid.uuid4())
    temp_file = f'{TEMP_FOLDER}/{unique_id}.mp4'
    compressed_file = f'{TEMP_FOLDER}/{unique_id}_compressed.mp4'
    cookie_file = get_cookie_file(url)

    # Формируем и запускаем yt-dlp с повторными попытками
    def build_command() -> list[str]:
        cmd = ['yt-dlp']
        if cookie_file:
            cmd += ['--cookies', cookie_file]
        cmd += ['-f', 'bestvideo+bestaudio/best', '--no-playlist', '--newline', '-o', temp_file]
        if 'instagram.com' in url:
            mobile_ua = (
                'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 '
                'Mobile/15E148 Safari/604.1'
            )
            cmd += ['--user-agent', mobile_ua, '--referer', 'https://www.instagram.com/']
        cmd += [url]
        return cmd

    max_attempts = 3
    last_err_text = ''

    try:
        for attempt in range(1, max_attempts + 1):
            command = build_command()
            logging.info(f"Запуск yt-dlp (попытка {attempt}): {' '.join(command)}")
            # Обновим статус на попытку скачивания
            try:
                await msg.edit_text(build_status('⏳ Скачиваю...', attempt, max_attempts))
            except Exception:
                pass
            # Потоковое отслеживание прогресса на stderr
            start_ts = time.monotonic()
            err_lines: list[str] = []
            percent_last: str | None = None
            last_update = 0.0
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            progress_re = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")
            try:
                while True:
                    # Таймаут 300с на попытку
                    if time.monotonic() - start_ts > 300:
                        proc.kill()
                        raise subprocess.TimeoutExpired(command, timeout=300)
                    # Читаем stderr, если доступно
                    if proc.stderr is None:
                        break
                    rlist, _, _ = select.select([proc.stderr], [], [], 0.5)
                    if rlist:
                        line = proc.stderr.readline()
                        if not line:
                            if proc.poll() is not None:
                                break
                            continue
                        err_lines.append(line)
                        m = progress_re.search(line)
                        if m:
                            percent = m.group(1)
                            now = time.monotonic()
                            if percent != percent_last and (now - last_update) >= 1.0:
                                try:
                                    await msg.edit_text(build_status('⏳ Скачиваю...', attempt, max_attempts, f'[{percent}%]'))
                                except Exception:
                                    pass
                                percent_last = percent
                                last_update = now
                    else:
                        if proc.poll() is not None:
                            break
                rc = proc.wait()
                if rc != 0:
                    last_err_text = ''.join(err_lines)
                    raise subprocess.CalledProcessError(rc, command, output='', stderr=last_err_text)
                # Успех
                try:
                    await msg.edit_text(build_status('✅ Загружено. Обработка файла...'))
                except Exception:
                    pass
                break
            finally:
                try:
                    if proc.stderr and not proc.stderr.closed:
                        proc.stderr.close()
                except Exception:
                    pass

        if not os.path.exists(temp_file):
            await msg.edit_text('❌ Видео не было загружено. Возможно, оно превышает лимит или недоступно.')
            return

        file_size = os.path.getsize(temp_file)
        if file_size > 50 * 1024 * 1024:
            try:
                await msg.edit_text(build_status('⚙️ Видео большое, перекодирую...'))
            except Exception:
                pass
            if not compress_video(temp_file, compressed_file):
                await msg.edit_text(build_status('❌ Не удалось перекодировать видео под лимит Telegram.'))
                return
            os.remove(temp_file)
            temp_file = compressed_file

        logging.info(f"Видео готово к отправке: {temp_file}")
        try:
            await msg.edit_text(build_status('📤 Отправляю видео...'))
        except Exception:
            pass

        with open(temp_file, 'rb') as video:
            await update.message.reply_video(video)

        # Увеличиваем счётчик успешных скачиваний
        increment_success()
        try:
            await msg.edit_text(build_status('✅ Готово.'))
        except Exception:
            pass

    except subprocess.TimeoutExpired:
        logging.error("Превышено время ожидания скачивания видео")
        increment_fail()
        await msg.edit_text(build_status('❌ Таймаут скачивания. Попробуйте позже.'))
    except subprocess.CalledProcessError as e:
        err_text = (last_err_text or e.stderr.decode('utf-8', errors='ignore')).strip()
        logging.error(f"Ошибка скачивания видео: {err_text}")
        increment_fail()
        low = err_text.lower()
        if ('login required' in low) or ('rate-limit' in low) or ('locked behind the login page' in low):
            # Короткое и понятное сообщение
            await msg.edit_text(build_status('❌ Instagram требует вход или лимит. Обновите cookies и повторите.'))
        else:
            await msg.edit_text(build_status('❌ Не удалось скачать. Повторите позже.'))
    except Exception as e:
        logging.exception("Непредвиденная ошибка")
        increment_fail()
        await msg.edit_text(build_status('❌ Непредвиденная ошибка. Повторите позже.'))
    finally:
        for f in [temp_file, compressed_file]:
            if os.path.exists(f):
                os.remove(f)

# Команда /start — приветствие и клавиатура
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton('Статистика')]], resize_keyboard=True
    )
    await update.message.reply_text(
        'Отправьте ссылку на видео из Instagram или YouTube.\n'
        'Нажмите «Статистика», чтобы увидеть количество скачиваний за сегодня, '
        'или используйте команду /stats.',
        reply_markup=keyboard
    )

# Команда и кнопка «Статистика»
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return
    await update.message.reply_text(f'Статистика: {get_stats_text()}')

# Точка входа
if __name__ == '__main__':
    if not TOKEN or not ALLOWED_USERS:
        raise ValueError("Переменные окружения BOT_TOKEN и ALLOWED_USER_IDS обязательны для запуска")

    app = ApplicationBuilder().token(TOKEN).build()
    # Команды
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stats', stats_command))
    # Кнопка «Статистика» (регистронезависимо)
    app.add_handler(MessageHandler(filters.Regex(re.compile(r'^статистика$', re.IGNORECASE)), stats_command))
    # Обработка ссылок
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_and_send_video))

    logging.info('Бот запущен...')
    app.run_polling()
