from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BroadcastRecoveryJob(Base):
    """Незавершённая рассылка (для предложения админу продолжить после рестарта)."""

    __tablename__ = "broadcast_recovery_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    payload_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    recipient_count_snap: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TelegramUser(Base):
    """Профиль пользователя Telegram для флагов бота (Single Source of Truth для политики ПДн)."""

    __tablename__ = "telegram_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_policy_accepted: Mapped[bool] = mapped_column(
        Boolean(),
        default=False,
        nullable=False,
        server_default="false",
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean(),
        default=False,
        nullable=False,
        server_default="false",
    )
    saved_fio: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    saved_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    saved_email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = ()


class PDConsent(Base):
    """Журнал согласий на обработку персональных данных (ФЗ-152)."""

    __tablename__ = "pd_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default="v1")

    __table_args__ = (
        Index("ix_pd_consents_telegram_user_id", "telegram_user_id"),
        Index("ix_pd_consents_consented_at", "consented_at"),
    )


class OpenDayApplication(Base):
    __tablename__ = "open_day_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fio: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")

    __table_args__ = (
        Index("ix_open_day_applications_telegram_user_id", "telegram_user_id"),
        Index("ix_open_day_applications_phone", "phone"),
        Index("ix_open_day_applications_email", "email"),
        Index("ix_open_day_applications_created_at", "created_at"),
        Index("ix_open_day_applications_status", "status"),
    )


class SpecialtyRequest(Base):
    __tablename__ = "specialty_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fio: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_result: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")

    __table_args__ = (
        Index("ix_specialty_requests_telegram_user_id", "telegram_user_id"),
        Index("ix_specialty_requests_phone", "phone"),
        Index("ix_specialty_requests_email", "email"),
        Index("ix_specialty_requests_created_at", "created_at"),
        Index("ix_specialty_requests_status", "status"),
    )
