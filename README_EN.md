Bot to download Instagram or YouTube videos and send them to Telegram as an attachment. Supports posts and Reels. Images are not supported.

Requirements
- Python packages: `python-telegram-bot`, `yt-dlp` (see `requirements.txt`)
- System dependency: `ffmpeg`
  - Ubuntu/Debian: `apt install ffmpeg`

Cookies
- Instagram: `cookie_instagram.txt` (do not store in the repository)
- YouTube: `cookie_youtube.txt` (do not store in the repository)

How to get cookies (and where to store)
1) Log into your account in a browser.
2) Install the “Get cookies.txt LOCALLY” extension.
3) Save cookies into local files (`cookie_instagram.txt` and/or `cookie_youtube.txt`) next to the project or in `secrets/`.
4) Do not commit these files — they are ignored by `.gitignore`.

Run
0) Build the image:
```
docker build -t telegram-bot .
```
1) Environment variables:
- `BOT_TOKEN` — your Telegram bot token from BotFather
- `ALLOWED_USER_IDS` — comma-separated list of Telegram user IDs allowed to use the bot (e.g. `12345,67890`).
  - Spaces and empty elements are ignored; invalid values are skipped.

2) Docker (recommended: mount cookie files as read-only):
```
docker run -d \
  -e BOT_TOKEN=your_token_here \
  -e ALLOWED_USER_IDS=123456789,1234567449 \
  -v $(pwd)/cookie_instagram.txt:/app/cookie_instagram.txt:ro \
  -v $(pwd)/cookie_youtube.txt:/app/cookie_youtube.txt:ro \
  telegram-bot
```
Simple run without cookies (if not needed):
```
docker run -d \
  -e BOT_TOKEN=your_token_here \
  -e ALLOWED_USER_IDS=123456789,1234567449 \
  telegram-bot
```

Usage
- Send the bot a link to an Instagram or YouTube video — it will download and send it as a Telegram video.
- If the file exceeds 50 MB, the bot will transcode it (down to ~640px width) to fit Telegram’s limit.
- “Statistics” button and `/stats` command show cumulative counts since container start: successful and failed downloads.
- For Instagram, the bot uses a mobile User-Agent and retries a few times for transient errors/rate limits.
- The bot keeps a “live status” message: one service message updated at each step (downloading with percent, retries, transcoding, sending) and shows current stats.

Notes
- Stats are in-memory and reset on container restart.

Security
- Do NOT commit cookies or tokens. `.gitignore` excludes `cookie_*.txt`, `secrets/`, and local artifacts.
- Cookies are optional for public videos but often required for private/limited content.
- Instagram may temporarily require login or throttle. If errors repeat, refresh `cookie_instagram.txt` and try again.
