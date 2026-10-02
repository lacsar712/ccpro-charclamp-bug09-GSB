from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 窑场本地时区（浏览器 datetime-local 输入采用此时区）。
LOCAL_TZ_NAME = "Asia/Shanghai"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """窑场本地时区的当前时刻（带时区）。"""
    return datetime.now(LOCAL_TZ)


def parse_local_started_at(raw: str | None) -> datetime:
    """
    将浏览器 datetime-local 提交的「本地墙上时间」解释为窑场时区时刻。

    datetime-local 本身不带时区，必须显式贴上 LOCAL_TZ，否则会被当成 UTC
    造成卡片时间与抽屉钟面整体错位。返回带时区的 datetime。
    """
    text = (raw or "").strip()
    parsed = datetime.fromisoformat(text) if text else local_now().replace(tzinfo=None)
    if parsed.tzinfo is not None:
        return parsed.astimezone(LOCAL_TZ)
    return parsed.replace(tzinfo=LOCAL_TZ)


def format_local(dt: datetime) -> str:
    """把带时区时刻格式化为窑场本地墙上时间，供卡片与钟面一致展示。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="worker")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    clamps: Mapped[list[Clamp]] = relationship(back_populates="site", cascade="all, delete-orphan")


class Clamp(Base):
    __tablename__ = "clamps"
    __table_args__ = (UniqueConstraint("site_id", "code", name="uq_clamp_code_per_site"),)

    STATUS_STACKED = "stacked"
    STATUS_BURNING = "burning"
    STATUS_DRAWN = "drawn"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_STACKED)
    wood_species: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    site: Mapped[Site] = relationship(back_populates="clamps")
    shifts: Mapped[list[BurnShift]] = relationship(
        back_populates="clamp",
        cascade="all, delete-orphan",
    )


class BurnShift(Base):
    __tablename__ = "burn_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clamp_id: Mapped[int] = mapped_column(ForeignKey("clamps.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    peak_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    charcoal_grade: Mapped[str] = mapped_column(String(40), nullable=False, default="B")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    clamp: Mapped[Clamp] = relationship(back_populates="shifts")
