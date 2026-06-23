<div align="center">

# Telegram Channel Parser

Parse Telegram channels, posts, comments, and media from a private local web app.

[Русская версия](README.ru.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-local_web_app-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## About

Telegram Channel Parser is an open-source, local-first app for saving Telegram
content in a structured format. Paste a link to a post or channel, choose
whether to download media, and follow the progress in a simple web interface.

The app uses your own Telegram API credentials and your own account. Your
session, database, parsed posts, and downloaded files stay on your computer.
There is no shared backend and no project-owner Telegram account involved.

## Features

- Parse a single Telegram post or an entire channel.
- Collect comments, authors, dates, and reply relationships.
- Download all media or select only photos, videos, video notes, GIFs, files,
  audio, voice messages, or stickers.
- Preview downloaded media directly in the browser.
- Pause and resume long channel imports.
- See progress and an estimated completion time.
- Export results as JSON or JSONL, with an optional media ZIP.
- Reopen previous imports from local history.
- Work with public channels and private channels you have already joined.
- Sign in by Telegram code or QR code.

## Built With

- [Python](https://www.python.org/)
- [Telethon](https://github.com/LonamiWebs/Telethon)
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLite](https://www.sqlite.org/)
- Jinja2 and vanilla JavaScript

## Getting Started

### Prerequisites

- Python 3.10 or newer
- A Telegram account
- Your own `api_id` and `api_hash` from
  [my.telegram.org/apps](https://my.telegram.org/apps)

A step-by-step guide for obtaining Telegram API credentials is available in
[`docs/TELEGRAM_API_SETUP.md`](docs/TELEGRAM_API_SETUP.md).

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/melswg/telegram-channel-parser.git
   cd telegram-channel-parser
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows:

   ```powershell
   .venv\Scripts\activate
   ```

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the app:

   ```bash
   python -m app.web
   ```

5. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Usage

On the first launch, the app will guide you through Telegram authorization:

1. Enter your `api_id` and `api_hash`.
2. Sign in with your phone number and Telegram code, or use QR login.
3. Paste a link to a post or channel.
4. Choose a post limit or leave it empty to parse the full channel.
5. Download all media or choose only the media types you need, then start the
   import.

Supported link formats include:

```text
https://t.me/example_channel/123
https://t.me/example_channel
https://t.me/c/123456789/42
```

Private `t.me/c/...` links work when the signed-in Telegram account is already
a member of that channel. The app does not join channels automatically.

## Exports

You can download a result while parsing is still in progress:

- **JSON** keeps posts and comments in a nested structure.
- **JSONL** stores one record per line for streaming and data processing.
- **ZIP with media** includes the structured data, a `media` directory, and a
  media manifest.

Parsed data is stored locally by default:

```text
data/parsed/<channel>/<post_id>/post.json
data/parsed/<channel>/<post_id>/media/
db.sqlite3
```

The storage directory can be changed from the app settings.

## Privacy and Security

Telegram Channel Parser is designed as a single-user local application.

- It listens on `127.0.0.1` by default.
- It performs read-only Telegram operations.
- It does not send messages, react to posts, or subscribe to channels.
- Login codes and 2FA passwords are never stored.
- Credentials and sessions are kept in ignored local files.

Never publish or share:

```text
.env
.local/
*.session
*.session-journal
api_hash
Telegram login codes
2FA passwords
```

A Telegram `.session` file can provide access to your account and should be
protected like a private key.

## Optional CLI

The web interface is the recommended way to use the project, but CLI commands
are also available:

```bash
python -m app.main parse-post https://t.me/example_channel/123 --media
python -m app.main parse-channel https://t.me/example_channel --limit 20 --media
python -m app.main info
```

Run `python -m app.main --help` to see all commands.

## Development

Run the test suite:

```bash
python -m pytest -q
```

Start the development server with auto-reload:

```bash
uvicorn app.web:app --host 127.0.0.1 --port 8000 --reload
```

## Roadmap

- Improve installation and packaging for non-technical users.
- Add more export options.
- Expand media handling and large-channel recovery tools.
- Continue improving Telegram authorization diagnostics.

See the [open issues](https://github.com/melswg/telegram-channel-parser/issues)
for planned work and known problems.

## Contributing

Issues and pull requests are welcome. For a larger change, please open an issue
first so the approach can be discussed.

1. Fork the repository.
2. Create a branch: `git checkout -b feature/my-feature`.
3. Commit your changes.
4. Push the branch and open a pull request.

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE).
