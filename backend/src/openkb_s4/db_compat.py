"""Dialect-portable upsert construct for PostgreSQL and SQLite deployments."""
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

from .config import get_settings


def insert(*args, **kwargs):
    """Return an Insert for the configured dialect with ON CONFLICT support."""
    if get_settings().database_url.startswith("sqlite"):
        return _sqlite_insert(*args, **kwargs)
    return _pg_insert(*args, **kwargs)
