#!/usr/bin/env python3
"""Telegram Comments Importer — CLI entrypoint.

Usage:
    python -m app.main init-session
    python -m app.main sync --channel @example --limit 50
    python -m app.main transcribe --workers 2
    python -m app.main export --format jsonl --out data/exports/comments.jsonl
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    name="telegram-comments",
    help="Import comments (including voice) from public Telegram channels.",
    no_args_is_help=True,
)

console = Console()


def setup_logging(verbose: bool = False):
    """Configure logging with Rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, markup=True)],
    )


def get_config():
    """Load config from .env, handling missing credentials gracefully."""
    from .config import load_config
    try:
        return load_config()
    except ValueError as e:
        console.print(f"[red]Ошибка конфигурации:[/red] {e}")
        console.print("Создайте/заполните [bold].env[/bold] файл на основе [bold].env.example[/bold]")
        raise typer.Exit(1)


# ── init-session ──────────────────────────────────────────────────────────

@app.command()
def init_session(
    session_name: str = typer.Option("telegram_importer", "--name", "-n",
                                      help="Session file name (without .session)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Интерактивная авторизация в Telegram. Создаёт session-файл."""
    setup_logging(verbose)

    from .config import load_config
    cfg = get_config()

    from .telegram import TelegramBackend
    import asyncio

    async def _init():
        tg = TelegramBackend(cfg.api_id, cfg.api_hash, session_name)
        me = await tg.start()
        console.print(f"[green]✓[/green] Авторизован как [bold]{me.username or me.phone or me.id}[/bold]")
        console.print(f"  session-файл: [bold]{session_name}.session[/bold]")
        await tg.stop()

    asyncio.run(_init())


# ── sync ──────────────────────────────────────────────────────────────────

@app.command()
def sync(
    channel: Optional[str] = typer.Option(None, "--channel", "-c",
                                            help="Public channel @username"),
    channel_list: Optional[Path] = typer.Option(None, "--channel-list", "-L",
                                                  help="File with channel usernames, one per line"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l",
                                         help="Max posts to fetch per channel"),
    since: Optional[str] = typer.Option(None, "--since",
                                          help="Date from: ISO format (2026-01-01)"),
    until: Optional[str] = typer.Option(None, "--until",
                                          help="Date to: ISO format"),
    resume: bool = typer.Option(False, "--resume", "-r",
                                 help="Resume from last synced post"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n",
                                  help="Only scan, don't save anything"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Синхронизировать посты и комментарии из канала(ов)."""
    setup_logging(verbose)
    cfg = get_config()

    # Determine channel list
    channels: list[str] = []
    if channel:
        channels.append(channel.lstrip("@"))
    if channel_list and channel_list.exists():
        with open(channel_list) as f:
            channels.extend(line.strip() for line in f if line.strip())
    if not channels:
        # Fall back to config
        channels = cfg.channels or None

    if not channels:
        console.print("[red]Не указаны каналы.[/red] Используйте --channel, --channel-list или CHANNELS в .env")
        raise typer.Exit(1)

    from .sync import run_sync

    async def _run():
        results = await run_sync(
            cfg, channels=channels, limit=limit,
            since=since, until=until,
            resume=resume, dry_run=dry_run,
        )
        for r in results:
            if r.get("dry_run"):
                console.print(f"  [bold]@{r['channel']}[/bold]: найдено {r.get('posts_found', 0)} постов")
            else:
                console.print(
                    f"  [bold]@{r['channel']}[/bold]: {r.get('posts', 0)} постов, "
                    f"{r.get('comments', 0)} комментариев, "
                    f"[yellow]{r.get('media_scheduled', 0)}[/yellow] голосовых скачано"
                )

    asyncio.run(_run())


# ── parse post/channel ───────────────────────────────────────────────────

def _parse_target_cli(
    url: str,
    expected_kind: str,
    limit: Optional[int] = 10,
    download_media: bool = False,
):
    cfg = get_config()
    from .db import Database
    from .parser import execute_parse_run
    from .targets import parse_telegram_target

    try:
        target = parse_telegram_target(url)
    except ValueError as exc:
        console.print(f"[red]Некорректная цель:[/red] {exc}")
        raise typer.Exit(1)
    if target.kind != expected_kind:
        console.print(
            f"[red]Ожидалась ссылка типа {expected_kind}, получено: {target.kind}.[/red]"
        )
        raise typer.Exit(1)

    db = Database(cfg.db_path)
    db.open()
    try:
        run_id = db.create_parse_run(
            target.canonical_url, target.kind, target.channel,
            total_posts=1 if target.kind == "post" else (limit or 0),
            download_media=download_media,
        )
    finally:
        db.close()

    result = asyncio.run(
        execute_parse_run(
            run_id,
            target,
            limit=limit,
            db_path=cfg.db_path,
            download_media=download_media,
        )
    )
    if result.get("status") == "failed":
        console.print(f"[red]Ошибка:[/red] {result.get('error', 'parse failed')}")
        raise typer.Exit(1)
    console.print(
        f"[green]Готово[/green]: {result.get('posts_count', 0)} постов, "
        f"{result.get('comments_count', 0)} комментариев"
    )
    console.print(f"Run: [bold]#{run_id}[/bold] · {result.get('save_path', '')}")


@app.command(name="parse-post")
def parse_post_command(
    url: str = typer.Argument(..., help="Ссылка вида https://t.me/channel/123"),
    media: bool = typer.Option(
        False, "--media", help="Скачать media в папку рядом с post.json"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Распарсить один Telegram-пост и его комментарии."""
    setup_logging(verbose)
    _parse_target_cli(url, expected_kind="post", limit=1, download_media=media)


@app.command(name="parse-channel")
def parse_channel_command(
    url: str = typer.Argument(..., help="Ссылка вида https://t.me/channel"),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", min=1,
        help="Последних постов; без параметра загружаются все",
    ),
    media: bool = typer.Option(
        False, "--media", help="Скачать media постов и комментариев"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Распарсить публикации канала и их комментарии."""
    setup_logging(verbose)
    _parse_target_cli(
        url,
        expected_kind="channel",
        limit=limit,
        download_media=media,
    )


# ── transcribe ────────────────────────────────────────────────────────────

@app.command()
def transcribe(
    model: str = typer.Option("base", "--model", "-m",
                               help="Whisper model size: tiny/base/small/medium/large-v3"),
    language: Optional[str] = typer.Option(None, "--language", "-l",
                                            help="Язык (например 'ru'). По умолчанию автоопределение"),
    force: bool = typer.Option(False, "--force", "-f",
                                help="Перетранскрибировать уже обработанные"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Транскрибировать необработанные голосовые сообщения."""
    setup_logging(verbose)
    cfg = get_config()

    from .sync import run_transcribe

    async def _run():
        stats = await run_transcribe(cfg, model_size=model, language=language, force=force)
        console.print(f"Транскрибировано: [green]{stats.get('transcribed', 0)}[/green] из {stats.get('total', 0)}")

    asyncio.run(_run())


# ── retry-download ────────────────────────────────────────────────────────

@app.command(name="retry-download")
def retry_download(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Повторно скачать голосовые, которые не удались в первый раз."""
    setup_logging(verbose)
    cfg = get_config()

    from .db import Database
    from .telegram import TelegramBackend
    from .sync import SyncEngine

    async def _run():
        db = Database(cfg.db_path)
        db.open()
        tg = TelegramBackend(cfg.api_id, cfg.api_hash, cfg.session_name)
        try:
            await tg.start()
            engine = SyncEngine(cfg, db, tg)
            stats = await engine.process_pending_media()
            console.print(f"Скачано: [green]{stats.get('downloaded', 0)}[/green], "
                         f"провалено: [red]{stats.get('failed', 0)}[/red]")
        finally:
            await tg.stop()
            db.close()

    asyncio.run(_run())


# ── export ────────────────────────────────────────────────────────────────

@app.command()
def export(
    fmt: str = typer.Option("jsonl", "--format", "-f",
                             help="Формат: jsonl или csv"),
    output: str = typer.Option("data/exports/comments.jsonl", "--out", "-o",
                                help="Путь для сохранения"),
    channel: Optional[str] = typer.Option(None, "--channel", "-c",
                                           help="Фильтр: только этот канал"),
    since: Optional[str] = typer.Option(None, "--since",
                                          help="Дата с (включительно)"),
    until: Optional[str] = typer.Option(None, "--until",
                                          help="Дата до (включительно)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Экспортировать комментарии + транскрипты в JSONL или CSV."""
    setup_logging(verbose)
    cfg = get_config()

    from .exporter import run_export

    count = run_export(cfg.db_path, fmt, output, channel=channel,
                       since=since, until=until)
    console.print(f"Экспортировано [green]{count}[/green] записей → [bold]{output}[/bold]")


# ── info ──────────────────────────────────────────────────────────────────

@app.command()
def info(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """Показать статистику по базе данных."""
    setup_logging(verbose)
    cfg = get_config()

    from .db import Database

    db = Database(cfg.db_path)
    db.open()

    try:
        cur = db.conn.execute("SELECT COUNT(*) FROM channels")
        channels = cur.fetchone()[0]
        cur = db.conn.execute("SELECT COUNT(*) FROM posts")
        posts = cur.fetchone()[0]
        cur = db.conn.execute("SELECT COUNT(*) FROM comments")
        comments = cur.fetchone()[0]
        cur = db.conn.execute("SELECT COUNT(*) FROM media")
        media = cur.fetchone()[0]
        cur = db.conn.execute("SELECT COUNT(*) FROM media WHERE download_status='downloaded'")
        media_done = cur.fetchone()[0]
        cur = db.conn.execute("SELECT COUNT(*) FROM transcripts")
        transcripts = cur.fetchone()[0]

        console.print("[bold]Статистика базы данных:[/bold]")
        console.print(f"  Каналов:        {channels}")
        console.print(f"  Постов:         {posts}")
        console.print(f"  Комментариев:   {comments}")
        console.print(f"  Медиа (всего):  {media}")
        console.print(f"  Медиа (скачано):{media_done}")
        console.print(f"  Транскриптов:   {transcripts}")

        if channels:
            console.print("\n[bold]Каналы:[/bold]")
            cur = db.conn.execute("SELECT username, title, last_post_id_seen FROM channels")
            for row in cur:
                console.print(f"  @{row[0]} — {row[1]} (last post: {row[2]})")
    finally:
        db.close()


# ── main ──────────────────────────────────────────────────────────────────

def main():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
