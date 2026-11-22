"""Dialect-portable upsert construct for PostgreSQL and SQLite deployments."""
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import Insert as PostgreSQLInsert
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import Insert as SQLiteInsert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


def insert(table: Table | type[DeclarativeBase]) -> PostgreSQLInsert | SQLiteInsert:
    """Return an Insert for the configured dialect with ON CONFLICT support."""
    if get_settings().database_url.startswith("sqlite"):
        return _sqlite_insert(table)
    return _pg_insert(table)
