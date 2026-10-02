from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from charclamp.domain.models import Base

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://charclamp:charclamp@127.0.0.1:6150/charclamp",
)
DATABASE_URL_SYNC = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg2://charclamp:charclamp@127.0.0.1:6150/charclamp",
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

sync_engine = create_engine(DATABASE_URL_SYNC, echo=False)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)


def sync_create_all() -> None:
    Base.metadata.create_all(sync_engine)


def purge_pending_stub_shifts() -> int:
    """清理旧版半提交遗留的空峰值残行（stub 指纹：未测峰值 + pending/?）。

    合法的「刚点火、未测峰值」班次 notes/grade 不同，不会被波及。
    """
    from sqlalchemy import delete

    from charclamp.domain.models import BurnShift

    with SyncSessionLocal() as session:
        result = session.execute(
            delete(BurnShift).where(
                BurnShift.peak_temp_c.is_(None),
                BurnShift.notes == "pending",
                BurnShift.charcoal_grade == "?",
            )
        )
        session.commit()
        return result.rowcount or 0


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
