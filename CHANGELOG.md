# Changelog

All notable changes to this project will be documented in this file.

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
