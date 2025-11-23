# Changelog

All notable changes to this project will be documented in this file.

## v1.1.0 - Music Download Feature

- **feat: Add song download via name or Spotify URL**: The bot can now download audio from YouTube. Users can send a plain text song name or a Spotify track link.
- **feat: Intelligent request routing**: A single message handler now determines the user's intent (video download, song download) based on the message content, removing the need for special commands.
- **refactor: YouTube search implementation**: Replaced the unstable `youtube-search-python` library with a more robust search-and-download mechanism using `yt-dlp`'s `ytsearch1:` feature. This resolves hanging and dependency conflict issues.
- **fix: Subprocess handling for audio downloads**: Reworked the audio download function to use a non-blocking process handler, preventing the bot from hanging during downloads.
- **chore: Docker configuration updates**:
    - `docker-compose.yml` now supports passing Spotify API credentials.
    - `Dockerfile` now includes `iputils-ping` to simplify network diagnostics.
- **docs: Update documentation**: All README files (`RU`, `EN`, `md`) have been updated to reflect the new functionality and configuration requirements.

## v1.0.0 – Initial public release

- Remove unused `llmbot.py` with hardcoded secrets.
- Add robust Instagram downloading:
  - Mobile User-Agent + referer
  - Up to 3 retries with exponential backoff
  - Improved short error messages
- Live status message with progress percentage and per-step updates.
- In-memory statistics (success/fail) shown in status and `/stats`.
- Safe parsing for `ALLOWED_USER_IDS`.
- Hide noisy `httpx` logs.
- Docker image and Docker Compose support.
- Documentation updates and `.gitignore` to keep cookies/tokens out of repo.
