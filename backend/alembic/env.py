"""Async Alembic migrations; dedicated owner URL never reaches the API."""
import asyncio
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from openkb_s4.config import get_settings
from openkb_s4.models import Base
from openkb_s4 import models_v13, models_handoff_v13  # noqa: F401

load_dotenv("../.env")
load_dotenv(".env")
target_metadata = Base.metadata


def offline() -> None:
    url = os.environ.get("S4_MIGRATION_DATABASE_URL", get_settings().database_url)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    url = os.environ.get("S4_MIGRATION_DATABASE_URL", get_settings().database_url)
    engine = create_async_engine(url)
    def migrate(connection: object) -> None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    offline()
else:
    asyncio.run(online())
