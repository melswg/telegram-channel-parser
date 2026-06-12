"""Local single-user FastAPI application."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .auth import TelegramAuthManager
from .db import Database
from .local_settings import LocalSettings, PROJECT_ROOT, validate_save_dir
from .models import now_iso
from .parser import execute_parse_run, preview_parse
from .targets import TelegramTarget, parse_telegram_target
from .web_exports import render_export, render_export_archive


APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv(
    "TELEGRAM_IMPORTER_DB_PATH",
    str(PROJECT_ROOT / "db.sqlite3"),
)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
auth_manager = TelegramAuthManager()
parse_lock = asyncio.Lock()
running_tasks: dict[int, asyncio.Task] = {}


def format_post_date(value: str | None) -> str:
    if not value:
        return "дата неизвестна"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)
    return parsed.strftime("%d.%m.%Y, %H:%M")


def publication_label(post: dict) -> str:
    number = post.get("publication_number")
    if number:
        return f"Публикация №{number}"
    return "Порядковый номер не рассчитан"


MEDIA_LABELS = {
    "voice": "Голосовое сообщение",
    "audio": "Аудио",
    "video": "Видео",
    "video_note": "Видеосообщение",
    "animation": "Анимация",
    "photo": "Фото",
    "image": "Изображение",
    "sticker": "Стикер",
    "document": "Документ",
    "web_preview": "Web preview",
    "other": "Media",
}


def format_media_duration(value: float | int | None) -> str:
    if value is None:
        return ""
    total_seconds = max(0, int(round(float(value))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def media_type_label(value: str | None) -> str:
    if not value:
        return "Media"
    return MEDIA_LABELS.get(value, str(value))


def media_description(post: dict) -> str:
    media = post.get("media") or {}
    media_type = media.get("type") or post.get("media_type")
    if not media_type:
        return ""
    label = media_type_label(media_type)
    duration = format_media_duration(media.get("duration"))
    if duration:
        return f"{label} {duration}"
    return label


def post_preview(post: dict) -> str:
    text = " ".join(str(post.get("text") or "").split())
    media_text = media_description(post)
    if text and media_text:
        return f"{text} · {media_text}"
    return text or media_text or "Публикация без текста"


def estimate_remaining_seconds(
    run: dict,
    current_time: datetime | None = None,
) -> int | None:
    processed = max(
        int(run.get("processed_posts") or 0),
        int(run.get("posts_count") or 0),
        int(run.get("observed_processed_posts") or 0),
    )
    total = int(run.get("total_posts") or 0)
    if run.get("status") not in {"running", "paused"}:
        return 0 if run.get("status") in {"success", "partial"} else None
    if processed <= 0 or total <= processed:
        return 0 if total and processed >= total else None
    try:
        started_at = datetime.fromisoformat(
            str(run.get("started_at") or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    now = current_time or datetime.now(timezone.utc)
    elapsed = max((now - started_at).total_seconds(), 1)
    return max(0, round((elapsed / processed) * (total - processed)))


def format_wait_time(seconds: int | None) -> str:
    if seconds is None:
        return "Оцениваем после первого обработанного поста…"
    if seconds <= 0:
        return "Завершается…"
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"Примерно {hours} ч {minutes} мин осталось"
    if hours:
        return f"Примерно {hours} ч осталось"
    return f"Примерно {minutes} мин осталось"


def enrich_run_estimate(run: dict) -> dict:
    run["processed_posts"] = max(
        int(run.get("processed_posts") or 0),
        int(run.get("posts_count") or 0),
        int(run.get("observed_processed_posts") or 0),
    )
    remaining = estimate_remaining_seconds(run)
    run["estimated_remaining_seconds"] = remaining
    status = run.get("status")
    if status in {"success", "partial"}:
        run["estimated_wait_text"] = "Парсинг завершён"
    elif status == "failed":
        run["estimated_wait_text"] = "Парсинг остановлен из-за ошибки"
    elif status == "queued":
        run["estimated_wait_text"] = "Ожидает запуска…"
    elif status == "paused":
        run["estimated_wait_text"] = "Парсинг на паузе"
    else:
        run["estimated_wait_text"] = format_wait_time(remaining)
    return run


def resolve_media_path(
    save_dir: Path,
    channel: str,
    post_id: int,
    filename: str,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", channel):
        raise ValueError("Некорректное имя канала.")
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("Некорректное имя media-файла.")
    media_dir = (save_dir / channel / str(post_id) / "media").resolve()
    path = (media_dir / filename).resolve()
    if path.parent != media_dir:
        raise ValueError("Media-файл находится вне разрешённой папки.")
    return path


templates.env.filters["post_date"] = format_post_date
templates.env.filters["publication_label"] = publication_label
templates.env.filters["post_preview"] = post_preview
templates.env.filters["media_duration"] = format_media_duration
templates.env.filters["media_type_label"] = media_type_label


def open_db() -> Database:
    db = Database(DB_PATH)
    db.open()
    return db


def template_context(request: Request, **values) -> dict:
    return {
        "request": request,
        "current_year": 2026,
        **values,
    }


def api_error(exc: Exception, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def post_back_target(post: dict, run: dict | None) -> tuple[str, str]:
    if run and run.get("target_type") == "channel":
        return f"/runs/{run['id']}", "← К постам канала"
    return "/", "← Назад к парсингу"


def _track_task(run_id: int, task: asyncio.Task) -> None:
    running_tasks[run_id] = task

    def remove_finished(finished: asyncio.Task) -> None:
        if running_tasks.get(run_id) is finished:
            running_tasks.pop(run_id, None)

    task.add_done_callback(remove_finished)


async def _run_queued_parse(
    run_id: int,
    target: TelegramTarget,
    limit: int | None,
    download_media: bool,
    resume: bool = False,
) -> None:
    async with parse_lock:
        await execute_parse_run(
            run_id,
            target,
            limit=limit,
            db_path=DB_PATH,
            download_media=download_media,
            resume=resume,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = LocalSettings.load_effective()
    Path(settings.session_path).parent.mkdir(parents=True, exist_ok=True)
    db = open_db()
    db.pause_interrupted_runs()
    db.close()
    yield
    if running_tasks:
        db = open_db()
        db.pause_interrupted_runs()
        db.close()
        tasks = list(running_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    await auth_manager.shutdown()


app = FastAPI(
    title="Telegram Comments Importer",
    description="Local-first read-only Telegram parser",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    fields = sorted(
        {
            str(item["loc"][-1])
            for item in exc.errors()
            if item.get("loc")
        }
    )
    field_text = ", ".join(fields) if fields else "одно или несколько полей"
    return JSONResponse(
        status_code=422,
        content={
            "detail": (
                f"Форма не прошла проверку. Почему: поля «{field_text}» пустые "
                "или имеют неверный формат. Что сделать: проверьте значения и "
                "повторите отправку."
            )
        },
    )


class CredentialsPayload(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=16, max_length=128)
    session_name: str = Field(default="telegram_importer", min_length=1, max_length=64)


class PhonePayload(BaseModel):
    phone: str


class CodePayload(BaseModel):
    code: str


class PasswordPayload(BaseModel):
    password: str


class CompleteLoginPayload(BaseModel):
    code: str
    password: str = ""


class StoragePayload(BaseModel):
    save_dir: str


class ResetPayload(BaseModel):
    confirm: bool = False


class ParsePayload(BaseModel):
    url: str
    limit: int | None = Field(default=10, ge=1)
    download_media: bool = False


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = LocalSettings.load_effective()
    db = open_db()
    try:
        runs = db.list_parse_runs(12)
        posts = db.list_parsed_posts(limit=8)
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=template_context(
            request,
            runs=runs,
            posts=posts,
            onboarding_required=(
                not settings.configured or not settings.session_file.exists()
            ),
            onboarding_step="telegram" if settings.configured else "credentials",
        ),
    )


@app.get("/setup")
async def setup_page():
    return RedirectResponse(url="/", status_code=307)


@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context=template_context(request),
    )


@app.get("/downloads/telegram-api-setup.md")
async def download_setup_guide():
    return FileResponse(
        PROJECT_ROOT / "docs" / "TELEGRAM_API_SETUP.md",
        media_type="text/markdown; charset=utf-8",
        filename="TELEGRAM_API_SETUP.md",
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=template_context(request, settings=LocalSettings.load_effective().public_dict()),
    )


@app.get("/media/{channel}/{post_id}/{filename}", name="serve_media")
async def serve_media(channel: str, post_id: int, filename: str):
    settings = LocalSettings.load_effective()
    try:
        path = resolve_media_path(
            validate_save_dir(settings.save_dir, create=False),
            channel,
            post_id,
            filename,
        )
    except ValueError as exc:
        raise api_error(exc) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "Media-файл не найден. Почему: файл не скачивался, был перемещён "
                "или удалён. Что сделать: повторите парсинг с включённым media."
            ),
        )
    response = FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@app.get("/posts/{channel}/{post_id}", response_class=HTMLResponse)
async def post_page(request: Request, channel: str, post_id: int):
    db = open_db()
    try:
        post = db.get_parsed_post(channel, post_id)
        run = (
            db.get_parse_run(post["last_run_id"])
            if post and post.get("last_run_id")
            else None
        )
    finally:
        db.close()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден в локальной истории.")
    back_url, back_label = post_back_target(post, run)
    return templates.TemplateResponse(
        request=request,
        name="post.html",
        context=template_context(
            request,
            post=post,
            back_url=back_url,
            back_label=back_label,
        ),
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_page(request: Request, run_id: int):
    db = open_db()
    try:
        run = db.get_parse_run(run_id)
    finally:
        db.close()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден.")
    enrich_run_estimate(run)
    return templates.TemplateResponse(
        request=request,
        name="run.html",
        context=template_context(request, run=run),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "time": now_iso(), "local_only": True}


@app.get("/api/status")
async def api_status():
    return await auth_manager.status()


@app.post("/api/setup/credentials")
async def save_credentials(payload: CredentialsPayload):
    settings = LocalSettings.load_effective()
    changing_existing = (
        settings.session_file.exists()
        and settings.configured
        and (
            settings.api_id != payload.api_id
            or settings.api_hash != payload.api_hash.strip()
            or settings.session_name != payload.session_name
        )
    )
    if changing_existing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Credentials нельзя заменить при существующей session. Почему: "
                "session связана с предыдущими api_id/api_hash. Что сделать: "
                "в настройках удалите данные входа, затем начните подключение заново."
            ),
        )
    try:
        await auth_manager.verify_credentials(
            payload.api_id, payload.api_hash.strip()
        )
        local = LocalSettings.load()
        local.update_credentials(
            payload.api_id, payload.api_hash, payload.session_name
        )
    except ValueError as exc:
        raise api_error(exc) from exc
    return local.public_dict()


@app.post("/api/setup/send-code")
async def send_code(payload: PhonePayload):
    try:
        return await auth_manager.send_code(payload.phone)
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/setup/resend-code")
async def resend_code():
    try:
        return await auth_manager.resend_code()
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/setup/qr-login")
async def start_qr_login():
    try:
        return await auth_manager.start_qr_login()
    except ValueError as exc:
        raise api_error(exc) from exc


@app.get("/api/setup/qr-login")
async def qr_login_status():
    return await auth_manager.qr_login_status()


@app.post("/api/setup/sign-in")
async def sign_in(payload: CodePayload):
    try:
        return await auth_manager.sign_in(payload.code)
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/setup/2fa")
async def sign_in_2fa(payload: PasswordPayload):
    try:
        return await auth_manager.sign_in_2fa(payload.password)
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/setup/complete-login")
async def complete_login(payload: CompleteLoginPayload):
    try:
        return await auth_manager.complete_login(payload.code, payload.password)
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/settings/storage")
async def save_storage(payload: StoragePayload):
    settings = LocalSettings.load()
    try:
        settings.update_save_dir(payload.save_dir)
    except (OSError, ValueError) as exc:
        raise api_error(exc) from exc
    return settings.public_dict()


@app.post("/api/settings/private")
async def private_settings():
    settings = LocalSettings.load_effective()
    response = JSONResponse(settings.private_dict())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@app.post("/api/setup/reset")
async def reset_session(payload: ResetPayload):
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Полный выход не выполнен. Почему: удаление credentials и session "
                "требует явного подтверждения."
            ),
        )
    try:
        return await auth_manager.reset()
    except ValueError as exc:
        raise api_error(exc, status_code=409) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Не удалось полностью удалить локальные данные входа. Почему: "
                f"операционная система вернула {type(exc).__name__}: {exc}. "
                "Что сделать: проверьте права на папку .local и повторите."
            ),
        ) from exc


async def enqueue_parse(payload: ParsePayload, required_kind: str | None = None):
    settings = LocalSettings.load_effective()
    if not settings.configured:
        raise HTTPException(
            status_code=409,
            detail=(
                "Импорт не запущен. Почему: на устройстве нет api_id и api_hash. "
                "Что сделать: пройдите первый шаг настройки."
            ),
        )
    if not settings.session_file.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "Импорт не запущен. Почему: локальная Telegram session не "
                "создана. Что сделать: войдите по номеру и коду."
            ),
        )
    try:
        target = parse_telegram_target(payload.url)
    except ValueError as exc:
        raise api_error(exc) from exc
    if required_kind and target.kind != required_kind:
        raise HTTPException(
            status_code=400,
            detail=f"Этот endpoint принимает только цель типа {required_kind}.",
        )
    limit = 1 if target.kind == "post" else payload.limit

    db = open_db()
    try:
        run_id = db.create_parse_run(
            target.canonical_url, target.kind, target.channel,
            total_posts=(limit or 0) if target.kind == "channel" else 1,
            download_media=payload.download_media,
        )
    finally:
        db.close()
    task = asyncio.create_task(
        _run_queued_parse(run_id, target, limit, payload.download_media)
    )
    _track_task(run_id, task)
    return {
        "run_id": run_id,
        "status": "queued",
        "target_type": target.kind,
        "url": target.canonical_url,
        "download_media": payload.download_media,
        "detail_url": f"/runs/{run_id}",
    }


@app.post("/api/parse/preview")
async def preview_parse_target(payload: ParsePayload):
    try:
        target = parse_telegram_target(payload.url)
        limit = 1 if target.kind == "post" else payload.limit
        return await preview_parse(target, limit, payload.download_media)
    except ValueError as exc:
        raise api_error(exc) from exc


@app.post("/api/parse", status_code=202)
async def parse_target(payload: ParsePayload):
    return await enqueue_parse(payload)


@app.post("/api/parse-post", status_code=202)
async def parse_post(payload: ParsePayload):
    return await enqueue_parse(payload, required_kind="post")


@app.post("/api/parse-channel", status_code=202)
async def parse_channel(payload: ParsePayload):
    return await enqueue_parse(payload, required_kind="channel")


@app.get("/api/posts")
async def list_posts(channel: str | None = None, limit: int = 100):
    db = open_db()
    try:
        return {"posts": db.list_parsed_posts(channel=channel, limit=min(limit, 500))}
    finally:
        db.close()


@app.get("/api/posts/{channel}/{post_id}")
async def get_post(channel: str, post_id: int):
    db = open_db()
    try:
        post = db.get_parsed_post(channel, post_id)
    finally:
        db.close()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден.")
    return post


@app.get("/api/runs")
async def list_runs(limit: int = 30):
    db = open_db()
    try:
        return {"runs": db.list_parse_runs(min(limit, 200))}
    finally:
        db.close()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int):
    db = open_db()
    try:
        run = db.get_parse_run(run_id)
    finally:
        db.close()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден.")
    return enrich_run_estimate(run)


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: int):
    db = open_db()
    try:
        run = db.get_parse_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Запуск не найден.")
        if run["status"] not in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Пауза недоступна. Почему: запуск уже остановлен или "
                    "завершён. Поставить на паузу можно только активный парсинг."
                ),
            )
        db.update_parse_run(run_id, status="paused", error="")
        return enrich_run_estimate(db.get_parse_run(run_id) or run)
    finally:
        db.close()


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: int):
    db = open_db()
    try:
        run = db.get_parse_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Запуск не найден.")
        if run["status"] != "paused":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Продолжение недоступно. Почему: запуск не находится "
                    "на паузе."
                ),
            )
        try:
            target = parse_telegram_target(run["source_url"])
        except ValueError as exc:
            raise api_error(exc) from exc
        limit = (
            1
            if target.kind == "post"
            else int(run["total_posts"]) or None
        )
        db.update_parse_run(run_id, status="running", error="")
        resumed = db.get_parse_run(run_id) or run
    finally:
        db.close()

    active_task = running_tasks.get(run_id)
    if not active_task or active_task.done():
        task = asyncio.create_task(
            _run_queued_parse(
                run_id,
                target,
                limit,
                bool(run["download_media"]),
                resume=True,
            )
        )
        _track_task(run_id, task)
    return enrich_run_estimate(resumed)


@app.get("/api/export/{scope}/{identifier}")
async def export_data(
    scope: Literal["post", "run", "channel"],
    identifier: str,
    format: Literal["json", "jsonl", "csv"] = "json",
    include_media: bool = False,
):
    db = open_db()
    try:
        if scope == "post":
            if ":" not in identifier:
                raise HTTPException(status_code=400, detail="Ожидается channel:post_id.")
            channel, raw_post_id = identifier.rsplit(":", 1)
            try:
                post_id = int(raw_post_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некорректный post_id.") from exc
            post = db.get_parsed_post(channel, post_id)
            posts = [post] if post else []
            filename = f"{channel}_{post_id}"
        elif scope == "run":
            try:
                run_id = int(identifier)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некорректный run id.") from exc
            run = db.get_parse_run(run_id)
            posts = []
            for item in (run or {}).get("posts", []):
                post = db.get_parsed_post(item["channel"], item["post_id"])
                if post:
                    posts.append(post)
            filename = f"run_{run_id}"
        else:
            posts = [
                db.get_parsed_post(item["channel"], item["post_id"])
                for item in db.list_parsed_posts(channel=identifier, limit=5000)
            ]
            posts = [post for post in posts if post]
            filename = identifier
    finally:
        db.close()

    if not posts:
        raise HTTPException(status_code=404, detail="Нет данных для экспорта.")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    if include_media:
        settings = LocalSettings.load_effective()
        try:
            content, media_type, _ = render_export_archive(
                posts,
                format,
                validate_save_dir(settings.save_dir, create=False),
            )
        except ValueError as exc:
            raise api_error(exc, status_code=409) from exc
        extension = "zip"
    else:
        content, media_type = render_export(posts, format)
        extension = format
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.{extension}"'
        },
    )


def main() -> None:
    import uvicorn

    uvicorn.run("app.web:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
