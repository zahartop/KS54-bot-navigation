"""Репозиторий данных пользователя и заявок: единственное место SQL/ORM доступа для хендлеров.

Запись согласия и анкеты на ДОД / специальность — в **одной** ACID-транзакции при финальной
отправке (согласие в журнал не попадает, пока анкета не сохранится).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models import (
    BroadcastRecoveryJob,
    OpenDayApplication,
    PDConsent,
    SpecialtyRequest,
    TelegramUser,
)
from src.data.session_scope import read_only_session, transactional_session
from src.monitoring import metrics as monitoring_metrics
from src.utils.date_tools import parse_user_date

logger = logging.getLogger(__name__)


def _is_missing_broadcast_recovery_table(exc: BaseException) -> bool:
    """True, если в цепочке исключений PostgreSQL/asyncpg жалуется на отсутствие таблицы recovery."""

    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        blob = str(cur).lower()
        if "broadcast_recovery_jobs" in blob and "does not exist" in blob:
            return True
        stack.append(cur.__cause__)
        stack.append(getattr(cur, "__context__", None))
        stack.append(getattr(cur, "orig", None))
    return False


class UserRepository:
    """Единый репозиторий: ПДн-согласия, анкеты, админские выборки."""

    def __init__(
        self,
        session_factory_provider: Callable[[], Any],
        write_max_retries: int = 3,
        write_retry_delay_seconds: int = 1,
        write_timeout_seconds: int = 10,
    ) -> None:
        """`session_factory_provider` вызывается без аргументов и должен возвращать **фабрику** сессий
        (например ``async_sessionmaker`` / вызываемый объект так, что ``factory()`` даёт async-context сессию).
        Так после ``dispose`` пула всегда можно получить актуальную factory через ``get_session_factory()`` в лямбде.
        """

        self._session_factory_provider = session_factory_provider
        self._write_max_retries = min(max(write_max_retries, 1), 3)
        self._write_retry_delay_seconds = max(write_retry_delay_seconds, 1)
        self._write_timeout_seconds = max(write_timeout_seconds, 1)

    def _sessions(self) -> Any:
        return self._session_factory_provider()

    # ─── Политика ПДн (флаг пользователя, Single Source of Truth) ────────────

    async def check_policy_status(self, telegram_user_id: int) -> bool:
        """Есть ли в БД активное подтверждение оферты/политики для Telegram user."""

        try:
            async with read_only_session(self._sessions()) as session:
                row = await asyncio.wait_for(
                    session.get(TelegramUser, telegram_user_id),
                    timeout=5.0,
                )
            return bool(row and row.is_policy_accepted)
        except asyncio.TimeoutError:
            logger.error("Timeout check_policy_status user_id=%s", telegram_user_id)
            return False
        except Exception:
            logger.exception("check_policy_status user_id=%s", telegram_user_id)
            return False

    async def is_telegram_user_admin(self, telegram_user_id: int) -> bool:
        """True, если в ``telegram_users`` выставлен флаг ``is_admin``."""

        try:
            async with read_only_session(self._sessions()) as session:
                row = await asyncio.wait_for(
                    session.get(TelegramUser, telegram_user_id),
                    timeout=5.0,
                )
            return bool(row and row.is_admin)
        except asyncio.TimeoutError:
            logger.error("Timeout is_telegram_user_admin user_id=%s", telegram_user_id)
            return False
        except Exception:
            logger.exception("is_telegram_user_admin user_id=%s", telegram_user_id)
            return False

    async def get_admin_telegram_user_ids(self) -> list[int]:
        """Все ``telegram_user_id`` с ``is_admin = true`` (для уведомлений и исключений из рассылки)."""

        try:
            async with read_only_session(self._sessions()) as session:
                rows = await asyncio.wait_for(
                    session.scalars(select(TelegramUser.telegram_user_id).where(TelegramUser.is_admin.is_(True))),
                    timeout=10.0,
                )
            return [int(x) for x in rows.all() if x is not None]
        except asyncio.TimeoutError:
            logger.error("Timeout get_admin_telegram_user_ids")
            return []
        except Exception:
            logger.exception("get_admin_telegram_user_ids")
            return []

    async def mark_policy_accepted(self, telegram_user_id: int) -> bool:
        """ACID: upsert строки пользователя и ``is_policy_accepted = TRUE``."""

        async def body(session: AsyncSession) -> None:
            stmt = (
                insert(TelegramUser.__table__)
                .values(
                    telegram_user_id=telegram_user_id,
                    is_policy_accepted=True,
                )
                .on_conflict_do_update(
                    index_elements=["telegram_user_id"],
                    set_={"is_policy_accepted": True},
                )
            )
            await session.execute(stmt)

        return await self._transactional_writes_with_retry(
            body,
            f"mark_policy_accepted user_id={telegram_user_id}",
        )

    # ─── Транзакции + retry ──────────────────────────────────────────────────

    async def _transactional_writes_with_retry(
        self,
        body: Callable[[AsyncSession], Awaitable[None]],
        log_context: str,
    ) -> bool:
        """Одна логическая запись с BEGIN/COMMIT (или полный ROLLBACK при ошибке)."""

        for attempt in range(1, self._write_max_retries + 1):
            try:

                async def _timed() -> None:
                    async with transactional_session(self._sessions()) as session:
                        await body(session)

                await asyncio.wait_for(_timed(), timeout=self._write_timeout_seconds)
                return True
            except (SQLAlchemyError, asyncio.TimeoutError) as exc:
                logger.exception(
                    "%s — ошибка записи БД (попытка %s/%s, timeout=%ss): %s",
                    log_context,
                    attempt,
                    self._write_max_retries,
                    self._write_timeout_seconds,
                    type(exc).__name__,
                )
                if attempt < self._write_max_retries:
                    backoff_delay = self._write_retry_delay_seconds * (2 ** (attempt - 1))
                    jitter = random.uniform(0, backoff_delay * 0.1)
                    monitoring_metrics.record_db_write_retry()
                    await asyncio.sleep(backoff_delay + jitter)
            except Exception:
                logger.exception("%s — неожиданная ошибка при записи в БД", log_context)
                return False

        logger.error(
            "%s — БД недоступна после %s попыток транзакции",
            log_context,
            self._write_max_retries,
        )
        return False

    # Совместимость с тестами (имитация backoff)
    async def _execute_with_retry(
        self,
        operation: Callable[[AsyncSession], Awaitable[None]],
        error_message: str,
    ) -> bool:
        """Устаревшее имя: одна транзакция через session.begin."""

        async def body(session: AsyncSession) -> None:
            await operation(session)

        return await self._transactional_writes_with_retry(body, error_message)

    # ─── ПДн: согласие (оферта) ───────────────────────────────────────────────

    async def save_consent(
        self,
        user_id: int,
        status: str,
        *,
        form_type: str = "unknown",
        policy_version: str = "v1",
    ) -> bool:
        """Фиксирует принятие оферты/согласия с временем на сервере.

        При ``declined`` в БД ничего не пишется (юридический отказ).
        Основной сценарий бота — атомарная запись через ``register_*`` после анкеты.
        """

        s = status.strip().lower()
        if s in ("declined", "reject", "rejected", "no"):
            logger.info("Согласие отклонено (без строки в pd_consents): user_id=%s", user_id)
            return True

        if s not in ("accepted", "accept", "yes"):
            logger.warning("Некорректный статус согласия %r для user_id=%s", status, user_id)
            return False

        ft = form_type[:20] if form_type else "unknown"
        pv = (policy_version or "v1")[:20]

        async def body(session: AsyncSession) -> None:
            session.add(
                PDConsent(
                    telegram_user_id=user_id,
                    form_type=ft,
                    policy_version=pv,
                )
            )

        return await self._transactional_writes_with_retry(
            body,
            f"save_consent user_id={user_id} form={ft}",
        )

    # ─── Сохранённый профиль (для повторных заявок) ─────────────────────────

    async def get_saved_profile(self, telegram_user_id: int) -> dict[str, str] | None:
        """Возвращает сохранённые ФИО/телефон/email или None."""
        try:
            async with read_only_session(self._sessions()) as session:
                row = await asyncio.wait_for(
                    session.get(TelegramUser, telegram_user_id),
                    timeout=5.0,
                )
            if row and row.saved_fio and row.saved_phone and row.saved_email:
                return {
                    "fio": row.saved_fio,
                    "phone": row.saved_phone,
                    "email": row.saved_email,
                }
            return None
        except Exception:
            logger.exception("get_saved_profile user_id=%s", telegram_user_id)
            return None

    async def _update_saved_profile(
        self, session: AsyncSession, telegram_user_id: int, fio: str, phone: str, email: str
    ) -> None:
        await session.execute(
            update(TelegramUser)
            .where(TelegramUser.telegram_user_id == telegram_user_id)
            .values(saved_fio=fio, saved_phone=phone, saved_email=email)
        )

    # ─── Регистрация абитуриента (анткета + согласие одной транзакцией) ───────

    async def register_abiturient(
        self,
        data: dict[str, Any],
    ) -> int | None:
        """Унифицированная точка входа: словарь с полем ``kind``.

        ``open_day``: telegram_user_id, fio, phone, email, open_day_date [, policy_version].
        ``specialty``: telegram_user_id, fio, phone, email, test_result [, request_date].
        """

        kind = data.get("kind")
        uid = data.get("telegram_user_id")

        if kind == "open_day":
            return await self.transactional_register_open_day(
                telegram_user_id=int(uid),
                fio=str(data["fio"]),
                phone=str(data["phone"]),
                email=str(data["email"]),
                open_day_date=str(data["open_day_date"]),
                form_type="open_day",
                policy_version=str(data.get("policy_version", "v1")),
            )
        if kind == "specialty":
            return await self.transactional_register_specialty(
                telegram_user_id=int(uid),
                fio=str(data["fio"]),
                phone=str(data["phone"]),
                email=str(data["email"]),
                test_result=str(data["test_result"]),
                form_type="specialty",
                policy_version=str(data.get("policy_version", "v1")),
                request_date=data.get("request_date"),
            )

        logger.error("register_abiturient: неизвестный kind=%r", kind)
        return None

    async def transactional_register_open_day(
        self,
        telegram_user_id: int,
        fio: str,
        phone: str,
        email: str,
        open_day_date: str,
        *,
        form_type: str = "open_day",
        policy_version: str = "v1",
    ) -> int | None:
        """ATOMIC: запись согласия + заявка ДОД. Либо обе строки, либо откат полностью."""

        parsed_date = parse_user_date(open_day_date)
        result: list[int | None] = [None]

        async def body(session: AsyncSession) -> None:
            result[0] = None
            session.add(
                PDConsent(
                    telegram_user_id=telegram_user_id,
                    form_type=(form_type or "open_day")[:20],
                    policy_version=(policy_version or "v1")[:20],
                )
            )
            app = OpenDayApplication(
                fio=fio,
                email=email,
                phone=phone,
                date=parsed_date,
                telegram_user_id=telegram_user_id,
            )
            session.add(app)
            await session.flush()
            result[0] = app.id
            await self._update_saved_profile(session, telegram_user_id, fio, phone, email)

        ok = await self._transactional_writes_with_retry(
            body,
            f"transactional_register_open_day user_id={telegram_user_id}",
        )
        return result[0] if ok else None

    async def transactional_register_specialty(
        self,
        telegram_user_id: int,
        fio: str,
        phone: str,
        email: str,
        test_result: str,
        *,
        form_type: str = "specialty",
        policy_version: str = "v1",
        request_date: str | None = None,
    ) -> int | None:
        """ATOMIC: согласие + заявка на подбор специальности."""

        raw_date = request_date or datetime.now(tz=timezone.utc).strftime("%d.%m.%Y")
        parsed_date = parse_user_date(raw_date)
        result: list[int | None] = [None]

        async def body(session: AsyncSession) -> None:
            result[0] = None
            session.add(
                PDConsent(
                    telegram_user_id=telegram_user_id,
                    form_type=(form_type or "specialty")[:20],
                    policy_version=(policy_version or "v1")[:20],
                )
            )
            rec = SpecialtyRequest(
                fio=fio,
                email=email,
                phone=phone,
                date=parsed_date,
                test_result=test_result[:10],
                telegram_user_id=telegram_user_id,
            )
            session.add(rec)
            await session.flush()
            result[0] = rec.id
            await self._update_saved_profile(session, telegram_user_id, fio, phone, email)

        ok = await self._transactional_writes_with_retry(
            body,
            f"transactional_register_specialty user_id={telegram_user_id}",
        )
        return result[0] if ok else None

    # ─── Дубликаты (read-only сессии) ───────────────────────────────────────────

    async def is_open_day_duplicate(self, telegram_user_id: int, open_day_date: str) -> bool:
        parsed_date = parse_user_date(open_day_date)
        try:
            async with read_only_session(self._sessions()) as session:
                count = await asyncio.wait_for(
                    session.scalar(
                        select(func.count())
                        .select_from(OpenDayApplication)
                        .where(
                            OpenDayApplication.telegram_user_id == telegram_user_id,
                            OpenDayApplication.date == parsed_date,
                        )
                    ),
                    timeout=5.0,
                )
                return (count or 0) > 0
        except asyncio.TimeoutError:
            logger.error("Timeout проверки дубля ДОД: user_id=%s", telegram_user_id)
            return False
        except Exception:
            logger.exception("Ошибка проверки дубля ДОД (user_id=%s)", telegram_user_id)
            return False

    async def is_specialty_duplicate(self, telegram_user_id: int, fio: str = "") -> bool:
        try:
            async with read_only_session(self._sessions()) as session:
                query = (
                    select(func.count())
                    .select_from(SpecialtyRequest)
                    .where(SpecialtyRequest.telegram_user_id == telegram_user_id)
                )
                if fio.strip():
                    query = query.where(SpecialtyRequest.fio == fio.strip())
                count = await asyncio.wait_for(session.scalar(query), timeout=5.0)
                return (count or 0) > 0
        except asyncio.TimeoutError:
            logger.error(
                "Timeout проверки дубля specialty: user_id=%s",
                telegram_user_id,
            )
            return False
        except Exception:
            logger.exception("Ошибка проверки дубля specialty (user_id=%s)", telegram_user_id)
            return False

    # ─── Обновление статуса (админка) ──────────────────────────────────────────

    async def update_application_status(self, app_type: str, app_id: int, status: str) -> bool:
        model_class = OpenDayApplication if app_type == "od" else SpecialtyRequest

        async def body(session: AsyncSession) -> None:
            row = await session.get(model_class, app_id)
            if row:
                row.status = status

        return await self._transactional_writes_with_retry(
            body,
            f"update_application_status {app_type}#{app_id}→{status}",
        )

    # ─── Выборки (админка) ────────────────────────────────────────────────────

    async def get_new_applications(self, limit: int = 10) -> list[dict]:
        try:
            async with read_only_session(self._sessions()) as session:
                oda_rows = (
                    await asyncio.wait_for(
                        session.scalars(
                            select(OpenDayApplication)
                            .where(OpenDayApplication.status == "new")
                            .order_by(OpenDayApplication.created_at.desc())
                            .limit(limit)
                        ),
                        timeout=5.0,
                    )
                ).all()
                sr_rows = (
                    await asyncio.wait_for(
                        session.scalars(
                            select(SpecialtyRequest)
                            .where(SpecialtyRequest.status == "new")
                            .order_by(SpecialtyRequest.created_at.desc())
                            .limit(limit)
                        ),
                        timeout=5.0,
                    )
                ).all()

            combined: list[dict] = []
            for r in oda_rows:
                combined.append(
                    {
                        "type": "od",
                        "id": r.id,
                        "fio": r.fio,
                        "phone": r.phone,
                        "detail": r.date.strftime("%d.%m.%Y") if r.date else "—",
                        "status": r.status,
                        "created_at": r.created_at,
                    }
                )
            for r in sr_rows:
                combined.append(
                    {
                        "type": "sp",
                        "id": r.id,
                        "fio": r.fio,
                        "phone": r.phone,
                        "detail": f"Тест: {r.test_result}",
                        "status": r.status,
                        "created_at": r.created_at,
                    }
                )
            combined.sort(
                key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            return combined[:limit]
        except asyncio.TimeoutError:
            logger.error("Timeout get_new_applications")
            return []
        except Exception:
            logger.exception("Ошибка get_new_applications")
            return []

    async def get_stats(self) -> dict[str, int]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
        try:
            async with read_only_session(self._sessions()) as session:
                open_day = (
                    await asyncio.wait_for(
                        session.scalar(
                            select(func.count())
                            .select_from(OpenDayApplication)
                            .where(OpenDayApplication.created_at >= cutoff)
                        ),
                        timeout=5.0,
                    )
                    or 0
                )
                specialty = (
                    await asyncio.wait_for(
                        session.scalar(
                            select(func.count())
                            .select_from(SpecialtyRequest)
                            .where(SpecialtyRequest.created_at >= cutoff)
                        ),
                        timeout=5.0,
                    )
                    or 0
                )
                consents = (
                    await asyncio.wait_for(
                        session.scalar(
                            select(func.count()).select_from(PDConsent).where(PDConsent.consented_at >= cutoff)
                        ),
                        timeout=5.0,
                    )
                    or 0
                )
            return {"open_day": open_day, "specialty": specialty, "consents": consents}
        except asyncio.TimeoutError:
            logger.error("Timeout get_stats")
            return {"open_day": 0, "specialty": 0, "consents": 0}
        except Exception:
            logger.exception("Ошибка get_stats")
            return {"open_day": 0, "specialty": 0, "consents": 0}

    async def get_applications_csv(self) -> str:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
        try:
            async with read_only_session(self._sessions()) as session:
                oda_rows = (
                    await session.scalars(
                        select(OpenDayApplication)
                        .where(OpenDayApplication.created_at >= cutoff)
                        .order_by(OpenDayApplication.created_at.desc())
                    )
                ).all()
                sr_rows = (
                    await session.scalars(
                        select(SpecialtyRequest)
                        .where(SpecialtyRequest.created_at >= cutoff)
                        .order_by(SpecialtyRequest.created_at.desc())
                    )
                ).all()
        except Exception:
            logger.exception("Ошибка CSV выгрузки")
            return ""

        output = io.StringIO()
        writer = csv.writer(output, dialect="excel")
        writer.writerow(
            [
                "Тип",
                "ID",
                "ФИО",
                "Телефон",
                "Email",
                "Дата/Результат",
                "Дата подачи",
                "TG UserID",
                "Статус",
            ]
        )
        _STATUS_RU = {"new": "Новая", "processed": "Обработана", "declined": "Отказ"}
        for r in oda_rows:
            writer.writerow(
                [
                    "ДОД",
                    r.id,
                    r.fio,
                    r.phone,
                    r.email,
                    r.date.strftime("%d.%m.%Y") if r.date else "",
                    r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                    r.telegram_user_id or "",
                    _STATUS_RU.get(r.status, r.status),
                ]
            )
        for r in sr_rows:
            writer.writerow(
                [
                    "Специальность",
                    r.id,
                    r.fio,
                    r.phone,
                    r.email,
                    r.test_result,
                    r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                    r.telegram_user_id or "",
                    _STATUS_RU.get(r.status, r.status),
                ]
            )
        return output.getvalue()

    async def export_applications_json(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        """Выгрузка заявок ДОД и специальностей в JSON (интеграция Docflow / REST)."""

        try:
            async with read_only_session(self._sessions()) as session:
                oda_rows = (
                    await session.scalars(
                        select(OpenDayApplication)
                        .order_by(OpenDayApplication.created_at.desc())
                        .limit(limit)
                    )
                ).all()
                sr_rows = (
                    await session.scalars(
                        select(SpecialtyRequest)
                        .order_by(SpecialtyRequest.created_at.desc())
                        .limit(limit)
                    )
                ).all()
        except Exception:
            logger.exception("export_applications_json")
            return []

        out: list[dict[str, Any]] = []
        for r in oda_rows:
            out.append(
                {
                    "type": "open_day",
                    "id": r.id,
                    "telegram_user_id": r.telegram_user_id,
                    "fio": r.fio,
                    "phone": r.phone,
                    "email": r.email,
                    "event_date": r.date.isoformat() if r.date else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "status": r.status,
                }
            )
        for r in sr_rows:
            out.append(
                {
                    "type": "specialty",
                    "id": r.id,
                    "telegram_user_id": r.telegram_user_id,
                    "fio": r.fio,
                    "phone": r.phone,
                    "email": r.email,
                    "test_result": r.test_result,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "status": r.status,
                }
            )
        return out

    # ─── Recovery рассылок (после рестарта / таймаута) ───────────────────────────

    async def open_broadcast_recovery_job(
        self,
        admin_chat_id: int,
        *,
        payload_text: str | None,
        payload_photo_file_id: str | None,
        recipient_count: int,
    ) -> int | None:
        """Помечает прежние незавершённые задачи этого админа как cancelled и создаёт активную."""

        holder: dict[str, int] = {}

        async def body(session: AsyncSession) -> None:
            await session.execute(
                update(BroadcastRecoveryJob)
                .where(
                    BroadcastRecoveryJob.admin_chat_id == admin_chat_id,
                    BroadcastRecoveryJob.status.not_in(["completed"]),
                )
                .values(status="cancelled", updated_at=func.now()),
            )
            row = BroadcastRecoveryJob(
                admin_chat_id=admin_chat_id,
                status="active",
                payload_text=payload_text,
                payload_photo_file_id=payload_photo_file_id or None,
                recipient_count_snap=recipient_count,
            )
            session.add(row)
            await session.flush()
            holder["id"] = int(row.id)

        ok = await self._transactional_writes_with_retry(
            body,
            f"open_broadcast_recovery_job admin_chat_id={admin_chat_id}",
        )
        return holder.get("id") if ok else None

    async def set_broadcast_recovery_job_status(self, job_id: int, status: str) -> bool:
        allowed = {"active", "completed", "cancelled", "interrupted"}
        if status not in allowed:
            return False

        async def body(session: AsyncSession) -> None:
            await session.execute(
                update(BroadcastRecoveryJob)
                .where(BroadcastRecoveryJob.id == job_id)
                .values(status=status, updated_at=func.now()),
            )

        return await self._transactional_writes_with_retry(
            body,
            f"set_broadcast_recovery_job_status job_id={job_id} status={status}",
        )

    async def get_broadcast_recovery_job(self, job_id: int) -> dict[str, Any] | None:
        try:
            async with read_only_session(self._sessions()) as session:
                row = await session.get(BroadcastRecoveryJob, job_id)
        except Exception as exc:
            if _is_missing_broadcast_recovery_table(exc):
                logger.warning(
                    "get_broadcast_recovery_job: нет таблицы broadcast_recovery_jobs (alembic upgrade head). job_id=%s",
                    job_id,
                )
                return None
            logger.exception("get_broadcast_recovery_job id=%s", job_id)
            return None
        if row is None:
            return None
        return {
            "id": row.id,
            "admin_chat_id": row.admin_chat_id,
            "status": row.status,
            "payload_text": row.payload_text,
            "payload_photo_file_id": row.payload_photo_file_id,
            "recipient_count_snap": row.recipient_count_snap,
        }

    async def list_resumable_broadcast_recovery_jobs(self) -> list[dict[str, Any]]:
        try:
            async with read_only_session(self._sessions()) as session:
                rows = (
                    await session.scalars(
                        select(BroadcastRecoveryJob)
                        .where(BroadcastRecoveryJob.status.in_(["active", "interrupted"]))
                        .order_by(BroadcastRecoveryJob.updated_at.desc())
                    )
                ).all()
        except Exception as exc:
            if _is_missing_broadcast_recovery_table(exc):
                logger.warning(
                    "Таблица broadcast_recovery_jobs ещё не создана — пропуск recovery-проверки. "
                    "Выполните: docker compose exec bot alembic upgrade head"
                )
                return []
            logger.exception("list_resumable_broadcast_recovery_jobs")
            return []

        return [
            {
                "id": r.id,
                "admin_chat_id": r.admin_chat_id,
                "status": r.status,
                "payload_text": r.payload_text,
                "payload_photo_file_id": r.payload_photo_file_id,
                "recipient_count_snap": r.recipient_count_snap,
            }
            for r in rows
        ]

    async def get_all_registered_telegram_user_ids(self) -> list[int]:
        """Все пользователи с известным ``telegram_user_id``: профиль + анкеты.

        Совместимо с историческим ``AdmissionRepository`` (алиас того же класса).
        """

        merged: set[int] = set()
        try:
            async with read_only_session(self._sessions()) as session:
                tg_rows = (
                    await asyncio.wait_for(
                        session.scalars(select(TelegramUser.telegram_user_id)),
                        timeout=10.0,
                    )
                ).all()
                merged.update(r for r in tg_rows if r is not None)

                od_rows = (
                    await asyncio.wait_for(
                        session.scalars(
                            select(OpenDayApplication.telegram_user_id).where(
                                OpenDayApplication.telegram_user_id.is_not(None)
                            )
                        ),
                        timeout=10.0,
                    )
                ).all()
                merged.update(int(x) for x in od_rows if x is not None)

                sr_rows = (
                    await asyncio.wait_for(
                        session.scalars(
                            select(SpecialtyRequest.telegram_user_id).where(
                                SpecialtyRequest.telegram_user_id.is_not(None)
                            )
                        ),
                        timeout=10.0,
                    )
                ).all()
                merged.update(int(x) for x in sr_rows if x is not None)
        except asyncio.TimeoutError:
            logger.error("Timeout get_all_registered_telegram_user_ids")
            return []
        except Exception:
            logger.exception("get_all_registered_telegram_user_ids")
            return []

        return sorted(merged)
