<div align="center">

# Telegram Channel Parser

Локальный веб-инструмент для парсинга Telegram-каналов, постов, комментариев и медиа.

[English](README.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-local_web_app-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## О проекте

Telegram Channel Parser — open-source local-first приложение для сохранения
контента Telegram в структурированном виде. Вставьте ссылку на пост или канал,
выберите, нужно ли скачивать медиа, и следите за процессом в простом
веб-интерфейсе.

Приложение использует ваши собственные данные Telegram API и ваш аккаунт.
Сессия, база данных, публикации и скачанные файлы остаются на вашем компьютере.
Общего сервера и аккаунта автора проекта нет.

## Возможности

- Парсинг отдельного Telegram-поста или целого канала.
- Сохранение комментариев, авторов, дат и связей между ответами.
- Скачивание всех медиа или только выбранных типов: фото, видео, кружков, GIF,
  файлов, аудио, голосовых сообщений и стикеров.
- Просмотр скачанных медиа прямо в браузере.
- Пауза и продолжение длительного парсинга каналов.
- Отображение прогресса и примерного времени завершения.
- Экспорт в JSON или JSONL, при необходимости — ZIP с медиа.
- Локальная история предыдущих запусков.
- Работа с публичными каналами и приватными каналами, на которые вы подписаны.
- Авторизация по коду Telegram или QR-коду.

## Технологии

- [Python](https://www.python.org/)
- [Telethon](https://github.com/LonamiWebs/Telethon)
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLite](https://www.sqlite.org/)
- Jinja2 и vanilla JavaScript

## Быстрый старт

### Что понадобится

- Python 3.10 или новее
- Аккаунт Telegram
- Собственные `api_id` и `api_hash`, полученные на
  [my.telegram.org/apps](https://my.telegram.org/apps)

Пошаговая инструкция по получению данных Telegram API находится в
[`docs/TELEGRAM_API_SETUP.md`](docs/TELEGRAM_API_SETUP.md).

### Установка

1. Клонируйте репозиторий:

   ```bash
   git clone https://github.com/melswg/telegram-channel-parser.git
   cd telegram-channel-parser
   ```

2. Создайте и активируйте виртуальное окружение:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   На Windows:

   ```powershell
   .venv\Scripts\activate
   ```

3. Установите зависимости:

   ```bash
   pip install -r requirements.txt
   ```

4. Запустите приложение:

   ```bash
   python -m app.web
   ```

5. Откройте [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Демо-режим для разработки интерфейса

Чтобы работать над frontend без `api_id`, `api_hash` и подключения к Telegram,
на Windows запустите `Start Demo.bat`. На macOS или Linux используйте:

```bash
TELEGRAM_IMPORTER_DEMO=1 python -m app.web
```

Демо-режим создаёт отдельную базу `.local/demo.sqlite3` с тестовыми запусками,
постами, комментариями и изображениями. Настоящая база и Telegram session не
изменяются. В верхнем меню активный режим отмечен меткой `DEMO DATA`.

## Использование

При первом запуске приложение проведёт вас через авторизацию в Telegram:

1. Введите свои `api_id` и `api_hash`.
2. Войдите по номеру телефона и коду Telegram либо используйте QR-код.
3. Вставьте ссылку на пост или канал.
4. Укажите количество постов или оставьте поле пустым для полного канала.
5. Выберите все медиа или только нужные типы и запустите парсинг.

Поддерживаются следующие форматы ссылок:

```text
https://t.me/example_channel/123
https://t.me/example_channel
https://t.me/c/123456789/42
```

Приватные ссылки `t.me/c/...` работают, если текущий Telegram-аккаунт уже
состоит в канале. Приложение не вступает в каналы автоматически.

## Экспорт

Результат можно скачать, не дожидаясь окончания парсинга:

- **JSON** сохраняет посты и комментарии во вложенной структуре.
- **JSONL** хранит по одной записи в строке и удобен для потоковой обработки.
- **ZIP с медиа** содержит данные, папку `media` и манифест файлов.

По умолчанию данные сохраняются локально:

```text
data/parsed/<channel>/<post_id>/post.json
data/parsed/<channel>/<post_id>/media/
db.sqlite3
```

Папку хранения можно изменить в настройках приложения.

## Приватность и безопасность

Telegram Channel Parser разработан как локальное однопользовательское
приложение.

- По умолчанию оно доступно только на `127.0.0.1`.
- Все операции с Telegram выполняются только для чтения.
- Приложение не отправляет сообщения, не ставит реакции и не подписывается на
  каналы.
- Коды входа и пароли 2FA не сохраняются.
- Credentials и сессия хранятся в локальных файлах, исключённых из Git.

Никогда не публикуйте и не передавайте:

```text
.env
.local/
*.session
*.session-journal
api_hash
коды входа Telegram
пароли 2FA
```

Файл Telegram `.session` может предоставить доступ к вашему аккаунту, поэтому
его следует защищать как приватный ключ.

## Дополнительный CLI

Для большинства задач рекомендуется веб-интерфейс, но проект также
поддерживает команды терминала:

```bash
python -m app.main parse-post https://t.me/example_channel/123 --media
python -m app.main parse-channel https://t.me/example_channel --limit 20 --media
python -m app.main info
```

Полный список команд: `python -m app.main --help`.

## Разработка

Запуск тестов:

```bash
python -m pytest -q
```

Запуск сервера для разработки с автоматической перезагрузкой:

```bash
uvicorn app.web:app --host 127.0.0.1 --port 8000 --reload
```

## Планы

- Упростить установку для пользователей без технического опыта.
- Добавить новые форматы экспорта.
- Расширить работу с медиа и восстановление больших запусков.
- Продолжить улучшать диагностику авторизации Telegram.

Актуальные планы и известные проблемы находятся в
[Issues](https://github.com/melswg/telegram-channel-parser/issues).

## Участие в разработке

Issues и pull requests приветствуются. Перед крупным изменением лучше сначала
создать issue и обсудить подход.

1. Сделайте fork репозитория.
2. Создайте ветку: `git checkout -b feature/my-feature`.
3. Закоммитьте изменения.
4. Отправьте ветку и откройте pull request.

## Лицензия

Проект распространяется по лицензии MIT. См. [`LICENSE`](LICENSE).
