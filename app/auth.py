"""Web-friendly Telegram authorization flow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from telethon import TelegramClient, errors, functions
from telethon.sessions import MemorySession
from telethon.tl import types

from .local_settings import LocalSettings, mask_phone


class TelegramAuthManager:
    """Keeps the short-lived send-code/sign-in client between HTTP requests."""

    def __init__(self) -> None:
        self.client: TelegramClient | None = None
        self.phone = ""
        self.phone_code_hash = ""
        self._lock = asyncio.Lock()

    async def _disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
        self.client = None

    async def _new_client(self, settings: LocalSettings) -> TelegramClient:
        await self._disconnect()
        if not settings.configured:
            raise ValueError(
                "Не сохранены api_id и api_hash. Почему: без credentials Telegram "
                "не может определить ваше приложение. Что сделать: вернитесь к "
                "первому шагу и введите собственные api_id и api_hash."
            )
        client = TelegramClient(
            settings.session_path,
            int(settings.api_id),
            settings.api_hash,
        )
        await client.connect()
        self.client = client
        return client

    @staticmethod
    def _user_dict(user) -> dict[str, Any]:
        return {
            "id": getattr(user, "id", None),
            "username": getattr(user, "username", None),
            "phone": getattr(user, "phone", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
        }

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        result = dict(user)
        if result.get("phone"):
            result["phone"] = mask_phone(str(result["phone"]))
        return result

    @staticmethod
    def _next_delivery_name(next_type: object | None) -> str:
        names = {
            types.auth.CodeTypeSms: "SMS",
            types.auth.CodeTypeCall: "звонок",
            types.auth.CodeTypeFlashCall: "flash-звонок",
            types.auth.CodeTypeMissedCall: "пропущенный звонок",
            types.auth.CodeTypeFragmentSms: "Fragment",
        }
        for code_type, name in names.items():
            if isinstance(next_type, code_type):
                return name
        return ""

    @classmethod
    def _code_delivery(cls, sent) -> dict[str, Any]:
        sent_type = getattr(sent, "type", None)
        delivery = "unknown"
        message = (
            "Telegram принял запрос кода, но не сообщил приложению понятный "
            "способ доставки. Проверьте официальный Telegram на других устройствах."
        )

        if isinstance(sent_type, types.auth.SentCodeTypeApp):
            delivery = "telegram_app"
            message = (
                "Код отправлен не по SMS, а сообщением в официальный чат "
                "«Telegram» на другом уже авторизованном устройстве. Откройте "
                "Telegram и найдите служебный чат от аккаунта 777000."
            )
        elif isinstance(sent_type, types.auth.SentCodeTypeSms):
            delivery = "sms"
            message = "Код отправлен по SMS на указанный номер."
        elif isinstance(sent_type, types.auth.SentCodeTypeCall):
            delivery = "call"
            message = "Код будет продиктован во входящем телефонном звонке."
        elif isinstance(sent_type, types.auth.SentCodeTypeFlashCall):
            delivery = "flash_call"
            message = (
                "Telegram использует короткий flash-звонок. Код определяется "
                "по номеру звонящего."
            )
        elif isinstance(sent_type, types.auth.SentCodeTypeMissedCall):
            delivery = "missed_call"
            message = (
                "Telegram отправит пропущенный звонок. Кодом являются последние "
                "цифры номера звонящего."
            )
        elif isinstance(sent_type, types.auth.SentCodeTypeEmailCode):
            delivery = "email"
            pattern = getattr(sent_type, "email_pattern", "")
            message = f"Код отправлен на привязанную почту {pattern}."
        elif isinstance(sent_type, types.auth.SentCodeTypeFragmentSms):
            delivery = "fragment"
            message = (
                "Код доступен через Fragment. Откройте ссылку, которую Telegram "
                "вернул для этого запроса."
            )
        elif isinstance(sent_type, types.auth.SentCodeTypeSmsWord):
            delivery = "sms_word"
            message = "Telegram отправил по SMS код в виде одного слова."
        elif isinstance(sent_type, types.auth.SentCodeTypeSmsPhrase):
            delivery = "sms_phrase"
            message = "Telegram отправил по SMS код в виде фразы."
        elif isinstance(sent_type, types.auth.SentCodeTypeFirebaseSms):
            delivery = "firebase_sms"
            message = (
                "Telegram выбрал Firebase SMS, доступный только официальным "
                "мобильным приложениям. Откройте официальный Telegram или "
                "повторите вход позже."
            )
        elif isinstance(sent_type, types.auth.SentCodeTypeSetUpEmailRequired):
            delivery = "email_setup_required"
            message = (
                "Telegram требует сначала настроить почту для кодов входа. "
                "Завершите настройку в официальном приложении Telegram."
            )

        timeout = getattr(sent, "timeout", None)
        next_delivery = cls._next_delivery_name(
            getattr(sent, "next_type", None)
        )
        if timeout and next_delivery:
            message += (
                f" Через {timeout} сек. Telegram может разрешить следующий "
                f"способ: {next_delivery}."
            )
        return {
            "delivery": delivery,
            "delivery_message": message,
            "retry_after": timeout,
            "next_delivery": next_delivery or None,
        }

    async def verify_credentials(self, api_id: int, api_hash: str) -> None:
        """Validate credentials with Telegram without creating a session file."""
        client = TelegramClient(MemorySession(), api_id, api_hash)
        try:
            await client.connect()
            await client(functions.help.GetConfigRequest())
        except errors.ApiIdInvalidError as exc:
            raise ValueError(
                "Telegram отклонил api_id/api_hash. Почему: одно из значений "
                "неверно, не относится к этому приложению или было скопировано "
                "не полностью. Что сделать: заново скопируйте оба значения с "
                "my.telegram.org."
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise ValueError(
                "Не удалось подключиться к Telegram. Почему: Telegram недоступен "
                "с этого устройства или отсутствует интернет-соединение. Что "
                "сделать: проверьте сеть и повторите попытку."
            ) from exc
        except errors.RPCError as exc:
            raise ValueError(
                "Telegram не подтвердил credentials. "
                f"Причина от Telegram: {type(exc).__name__}. Что сделать: "
                "проверьте api_id/api_hash и повторите попытку."
            ) from exc
        finally:
            await client.disconnect()

    async def status(self) -> dict[str, Any]:
        settings = LocalSettings.load_effective()
        result = settings.public_dict()
        result["authenticated"] = False
        result["state"] = "not_configured"
        if not settings.configured:
            result["reason"] = (
                "На этом устройстве не сохранены api_id и api_hash. "
                "Пройдите первый шаг настройки."
            )
            return result
        result["state"] = "needs_login"
        if not settings.session_file.exists():
            result["reason"] = (
                "api_id и api_hash сохранены, но локальная Telegram session "
                "ещё не создана. Войдите по номеру и коду."
            )
            return result

        async with self._lock:
            try:
                client = await self._new_client(settings)
                if await client.is_user_authorized():
                    user = await client.get_me()
                    user_data = self._user_dict(user)
                    local = LocalSettings.load()
                    local.authorized_user = user_data
                    local.save()
                    result["user"] = self._public_user(user_data)
                    result["authenticated"] = True
                    result["state"] = "authorized"
            except (OSError, errors.RPCError) as exc:
                result["state"] = "session_error"
                result["reason"] = (
                    "Telegram session найдена, но её не удалось открыть или "
                    "проверить. "
                    f"Техническая причина: {type(exc).__name__}. Выполните полный "
                    "выход в настройках и войдите заново."
                )
            finally:
                await self._disconnect()
        return result

    async def send_code(self, phone: str) -> dict[str, Any]:
        phone = (phone or "").strip()
        if not phone.startswith("+") or len(phone) < 8:
            raise ValueError(
                "Номер не прошёл локальную проверку. Почему: он должен начинаться "
                "с «+» и содержать код страны. Что сделать: введите номер в "
                "международном формате, например +79991234567."
            )
        settings = LocalSettings.load_effective()
        async with self._lock:
            try:
                client = await self._new_client(settings)
                if await client.is_user_authorized():
                    user = await client.get_me()
                    local = LocalSettings.load()
                    local.authorized_user = self._user_dict(user)
                    local.save()
                    await self._disconnect()
                    return {
                        "state": "authorized",
                        "user": self._public_user(local.authorized_user),
                    }
                sent = await client.send_code_request(phone)
                self.phone = phone
                self.phone_code_hash = sent.phone_code_hash
                return {
                    "state": "code_sent",
                    **self._code_delivery(sent),
                }
            except errors.FloodWaitError as exc:
                await self._disconnect()
                raise ValueError(
                    f"Telegram временно ограничил запросы. Почему: было слишком "
                    f"много попыток входа. Что сделать: подождите {exc.seconds} "
                    "сек. и повторите."
                ) from exc
            except errors.PhoneNumberInvalidError as exc:
                await self._disconnect()
                raise ValueError(
                    "Telegram не принял номер. Почему: номер имеет неверный формат "
                    "или не распознан Telegram. Что сделать: проверьте код страны "
                    "и сам номер, затем повторите."
                ) from exc
            except errors.ApiIdInvalidError as exc:
                await self._disconnect()
                raise ValueError(
                    "Telegram отклонил api_id/api_hash. Почему: сохранённые "
                    "credentials неверны или больше не действуют. Что сделать: "
                    "выполните полный выход и введите собственные данные заново."
                ) from exc
            except (ConnectionError, OSError) as exc:
                await self._disconnect()
                raise ValueError(
                    "Код не отправлен. Почему: не удалось связаться с Telegram. "
                    "Что сделать: проверьте интернет и повторите попытку."
                ) from exc
            except errors.RPCError as exc:
                await self._disconnect()
                raise ValueError(
                    "Telegram не смог отправить код. "
                    f"Причина от Telegram: {type(exc).__name__}. Что сделать: "
                    "проверьте номер и повторите попытку позже."
                ) from exc

    async def sign_in(self, code: str) -> dict[str, Any]:
        code = "".join((code or "").split())
        if not code:
            raise ValueError(
                "Код не введён. Что сделать: откройте официальный клиент "
                "Telegram и введите полученный код."
            )
        async with self._lock:
            if not self.client or not self.phone_code_hash:
                raise ValueError(
                    "Запрос кода больше не активен. Почему: локальный сервер был "
                    "перезапущен или вход начат заново. Что сделать: снова укажите "
                    "номер и запросите новый код."
                )
            try:
                user = await self.client.sign_in(
                    phone=self.phone,
                    code=code,
                    phone_code_hash=self.phone_code_hash,
                )
            except errors.SessionPasswordNeededError:
                return {"state": "2fa_required"}
            except errors.PhoneCodeInvalidError as exc:
                raise ValueError(
                    "Telegram отклонил код. Почему: код введён неверно. Что "
                    "сделать: проверьте последнее сообщение Telegram и повторите."
                ) from exc
            except errors.PhoneCodeExpiredError as exc:
                await self._disconnect()
                raise ValueError(
                    "Код истёк. Почему: срок действия кода Telegram закончился. "
                    "Что сделать: вернитесь к номеру и запросите новый код."
                ) from exc
            except errors.FloodWaitError as exc:
                raise ValueError(
                    f"Telegram временно ограничил попытки. Что сделать: подождите "
                    f"{exc.seconds} сек. и повторите."
                ) from exc
            except (ConnectionError, OSError) as exc:
                await self._disconnect()
                raise ValueError(
                    "Вход прервался. Почему: локальный сервер потерял соединение "
                    "с Telegram во время проверки кода. Что сделать: проверьте "
                    "интернет, запросите новый код и повторите вход."
                ) from exc
            except errors.RPCError as exc:
                raise ValueError(
                    "Telegram не завершил вход по коду. "
                    f"Причина от Telegram: {type(exc).__name__}. Что сделать: "
                    "запросите новый код и повторите."
                ) from exc
            return await self._complete(user)

    async def sign_in_2fa(self, password: str) -> dict[str, Any]:
        if not password:
            raise ValueError(
                "Telegram требует пароль 2FA, но поле пустое. Что сделать: "
                "введите облачный пароль Telegram и повторите."
            )
        async with self._lock:
            if not self.client:
                raise ValueError(
                    "Сессия входа истекла. Почему: локальный сервер потерял "
                    "временный запрос авторизации. Что сделать: запросите код заново."
                )
            try:
                user = await self.client.sign_in(password=password)
            except errors.PasswordHashInvalidError as exc:
                raise ValueError(
                    "Telegram отклонил пароль 2FA. Почему: облачный пароль введён "
                    "неверно. Что сделать: проверьте пароль и повторите."
                ) from exc
            except errors.FloodWaitError as exc:
                raise ValueError(
                    f"Telegram временно ограничил попытки. Что сделать: подождите "
                    f"{exc.seconds} сек. и повторите."
                ) from exc
            except (ConnectionError, OSError) as exc:
                await self._disconnect()
                raise ValueError(
                    "Проверка 2FA прервалась. Почему: потеряно соединение с "
                    "Telegram. Что сделать: проверьте интернет и начните вход заново."
                ) from exc
            except errors.RPCError as exc:
                raise ValueError(
                    "Telegram не завершил проверку 2FA. "
                    f"Причина от Telegram: {type(exc).__name__}. Что сделать: "
                    "проверьте пароль или начните вход заново."
                ) from exc
            return await self._complete(user)

    async def complete_login(self, code: str, password: str = "") -> dict[str, Any]:
        result = await self.sign_in(code)
        if result.get("state") != "2fa_required":
            return result
        if not password:
            return result
        return await self.sign_in_2fa(password)

    async def _complete(self, user) -> dict[str, Any]:
        settings = LocalSettings.load()
        settings.authorized_user = self._user_dict(user)
        settings.save()
        await self._disconnect()
        self.phone = ""
        self.phone_code_hash = ""
        return {
            "state": "authorized",
            "user": self._public_user(settings.authorized_user),
        }

    async def reset(self) -> dict[str, Any]:
        settings = LocalSettings.load_effective()
        async with self._lock:
            await self._disconnect()
            remote_logout = "not_needed"
            if settings.configured and settings.session_file.exists():
                try:
                    client = await self._new_client(settings)
                    if await client.is_user_authorized():
                        if not await client.log_out():
                            raise ValueError(
                                "Telegram не подтвердил завершение авторизации. "
                                "Локальные данные сохранены, чтобы можно было "
                                "повторить попытку и не оставить скрытый активный вход."
                            )
                        self.client = None
                        remote_logout = "revoked"
                    else:
                        remote_logout = "already_inactive"
                except errors.AuthKeyUnregisteredError:
                    remote_logout = "already_inactive"
                except errors.FloodWaitError as exc:
                    raise ValueError(
                        "Полный выход пока не выполнен. Почему: Telegram временно "
                        f"ограничил запросы. Что сделать: подождите {exc.seconds} "
                        "сек. и нажмите кнопку ещё раз."
                    ) from exc
                except (ConnectionError, OSError) as exc:
                    raise ValueError(
                        "Полный выход пока не выполнен. Почему: не удалось "
                        "связаться с Telegram и отозвать вход в списке устройств. "
                        "Локальные данные не удалены. Что сделать: проверьте "
                        "интернет и повторите."
                    ) from exc
                except errors.RPCError as exc:
                    raise ValueError(
                        "Полный выход пока не выполнен. Telegram не отозвал "
                        f"авторизацию: {type(exc).__name__}. Локальные данные "
                        "сохранены; повторите позже."
                    ) from exc
                finally:
                    await self._disconnect()

            removed_files: list[str] = []
            for suffix in (".session", ".session-journal", ".session-wal", ".session-shm"):
                path = Path(f"{settings.session_path}{suffix}")
                if path.exists():
                    path.unlink()
                    removed_files.append(path.name)
            local = LocalSettings.load()
            had_credentials = local.configured or settings.configured
            had_profile = bool(local.authorized_user)
            local.clear_telegram_identity()
            self.phone = ""
            self.phone_code_hash = ""
            return {
                "status": "reset",
                "removed": {
                    "session_files": removed_files,
                    "credentials": had_credentials,
                    "profile": had_profile,
                },
                "remote_logout": remote_logout,
                "message": (
                    "Вход отозван в Telegram. Локальная session, api_id, api_hash "
                    "и данные профиля удалены. История парсинга и папка "
                    "результатов сохранены."
                    if remote_logout == "revoked"
                    else
                    "Telegram уже считал эту авторизацию неактивной. Локальная "
                    "session, api_id, api_hash и данные профиля удалены."
                ),
            }
