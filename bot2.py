import glob
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

# Config from environment
TOKEN = os.getenv('BOT_TOKEN')
TEMP_FOLDER = './temp'

# Safe ALLOWED_USER_IDS parser (comma-separated; ignores blanks/invalid)
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
            logging.warning(f"Skipping invalid user id: {part}")
    return users

ALLOWED_USERS = parse_allowed_users(os.getenv('ALLOWED_USER_IDS', ''))

# In-memory stats for process lifetime (reset on container restart)
TOTAL_SUCCESS = 0
TOTAL_FAIL = 0

logging.basicConfig(level=logging.INFO)
# Hide noisy Telegram HTTP logs (httpx)
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)
httpx_logger.disabled = True
class _NoHttpxFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        return not record.name.startswith('httpx')
logging.getLogger().addFilter(_NoHttpxFilter())

# Ensure temp folder exists
os.makedirs(TEMP_FOLDER, exist_ok=True)

def increment_success() -> None:
    global TOTAL_SUCCESS
    TOTAL_SUCCESS += 1

def increment_fail() -> None:
    global TOTAL_FAIL
    TOTAL_FAIL += 1

def get_stats_text() -> str:
    return f"success: {TOTAL_SUCCESS}, failures: {TOTAL_FAIL}"

def build_status(stage: str, attempt: int | None = None, max_attempts: int | None = None, progress: str | None = None) -> str:
    parts = [stage]
    if attempt and max_attempts:
        parts.append(f"(try {attempt}/{max_attempts})")
    if progress:
        parts.append(progress)
    parts.append(f"— {get_stats_text()}")
    return ' '.join(parts)

# Select cookie file by URL
def get_cookie_file(url: str) -> str:
    if 'instagram.com' in url:
        return './cookie_instagram.txt'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return './cookie_youtube.txt'
    return ''

# Transcode video to fit Telegram limit
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
        logging.error(f"Video transcode error: {e}")
        return False

# Download and send video
async def download_and_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text('⛔️ You are not allowed to use this bot.')
        logging.warning(f"Access denied for user_id: {user_id}")
        return

    url = update.message.text
    msg = await update.message.reply_text(build_status('⏳ Downloading video...'))

    unique_id = str(uuid.uuid4())
    temp_file = f'{TEMP_FOLDER}/{unique_id}.mp4'
    compressed_file = f'{TEMP_FOLDER}/{unique_id}_compressed.mp4'
    cookie_file = get_cookie_file(url)

    # Build and run yt-dlp with retries
    def build_command() -> list[str]:
        cmd = ['yt-dlp']
        if cookie_file:
            cmd += ['--cookies', cookie_file]
        cmd += [
            '-f', 'bestvideo+bestaudio/best',
            '--merge-output-format', 'mp4',
            '--no-playlist',
            '--newline',
            '-o', temp_file
        ]
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
            logging.info(f"Starting yt-dlp (attempt {attempt}): {' '.join(command)}")
            # Обновим статус на попытку скачивания
            try:
                await msg.edit_text(build_status('⏳ Downloading...', attempt, max_attempts))
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
                                    await msg.edit_text(build_status('⏳ Downloading...', attempt, max_attempts, f'[{percent}%]'))
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
                # Success
                try:
                    await msg.edit_text(build_status('✅ Downloaded. Processing file...'))
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
            fallback_matches = [
                path for path in glob.glob(f'{TEMP_FOLDER}/{unique_id}.*')
                if not path.endswith('.part')
            ]
            if fallback_matches:
                fallback_matches.sort(key=os.path.getsize, reverse=True)
                temp_file = fallback_matches[0]
            else:
                await msg.edit_text('❌ Video was not downloaded. It may exceed the limit or be unavailable.')
                return

        if not os.path.exists(temp_file):
            await msg.edit_text('❌ Video was not downloaded. It may exceed the limit or be unavailable.')
            return

        file_size = os.path.getsize(temp_file)
        if file_size > 50 * 1024 * 1024:
            try:
                await msg.edit_text(build_status('⚙️ Large video, transcoding...'))
            except Exception:
                pass
            if not compress_video(temp_file, compressed_file):
                await msg.edit_text(build_status('❌ Failed to transcode video to fit Telegram limit.'))
                return
            os.remove(temp_file)
            temp_file = compressed_file

        logging.info(f"Video ready to send: {temp_file}")
        try:
            await msg.edit_text(build_status('📤 Uploading video...'))
        except Exception:
            pass

        with open(temp_file, 'rb') as video:
            await update.message.reply_video(video)

        # Increase success counter
        increment_success()
        try:
            await msg.edit_text(build_status('✅ Done.'))
        except Exception:
            pass

    except subprocess.TimeoutExpired:
        logging.error("Download timeout")
        increment_fail()
        await msg.edit_text(build_status('❌ Download timeout. Try again later.'))
    except subprocess.CalledProcessError as e:
        err_text = (last_err_text or e.stderr.decode('utf-8', errors='ignore')).strip()
        logging.error(f"Video download error: {err_text}")
        increment_fail()
        low = err_text.lower()
        if ('login required' in low) or ('rate-limit' in low) or ('locked behind the login page' in low):
            # Short and clear message
            await msg.edit_text(build_status('❌ Instagram login required or rate limit. Update cookies and retry.'))
        else:
            await msg.edit_text(build_status('❌ Failed to download. Try again later.'))
    except Exception as e:
        logging.exception("Unexpected error")
        increment_fail()
        await msg.edit_text(build_status('❌ Unexpected error. Try again later.'))
    finally:
        for f in [temp_file, compressed_file]:
            if os.path.exists(f):
                os.remove(f)

# /start — greeting and keyboard
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton('Stats')]], resize_keyboard=True
    )
    await update.message.reply_text(
        'Send a link to an Instagram or YouTube video.\n'
        'Tap “Stats” to see totals since start, or use /stats.',
        reply_markup=keyboard
    )

# /stats and “Stats” button
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return
    await update.message.reply_text(f'Stats: {get_stats_text()}')

# Точка входа
if __name__ == '__main__':
    if not TOKEN or not ALLOWED_USERS:
        raise ValueError("Environment variables BOT_TOKEN and ALLOWED_USER_IDS are required")

    app = ApplicationBuilder().token(TOKEN).build()
    # Commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stats', stats_command))
    # Stats button (case-insensitive)
    app.add_handler(MessageHandler(filters.Regex(re.compile(r'^stats$', re.IGNORECASE)), stats_command))
    # Handle links
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_and_send_video))

    logging.info('Bot started...')
    app.run_polling()
