"""Integrity traversal for a DB snapshot's private immutable content references."""
import json
import re
from typing import Any

from .content_store import ContentStore


def references_in(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if set(value) == {"object_key", "sha256"}:
            return [value]
        return [ref for item in value.values() for ref in references_in(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in references_in(item)]
    return []


def verify_controlled_graph(store: ContentStore, roots: list[dict[str, Any]]) -> int:
    pending = list(roots)
    visited: set[str] = set()
    while pending:
        reference = pending.pop()
        store.validate_reference(reference)
        if reference["object_key"] in visited:
            continue
        value = store.read_json(reference)
        visited.add(reference["object_key"])
        pending.extend(references_in(value))
    return len(visited)


async def database_references(connection: Any) -> list[dict[str, Any]]:
    """Use the caller's exported PostgreSQL snapshot; never open another read."""
    columns = await connection.fetch("""SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name LIKE 'v13_%' AND column_name LIKE '%_ref'
        AND data_type IN ('json','jsonb') ORDER BY table_name,column_name""")
    result = []
    for row in columns:
        table, column = row["table_name"], row["column_name"]
        if not all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in (table, column)):
            raise ValueError("Unexpected index identifier")
        for record in await connection.fetch(f'SELECT "{column}" AS value FROM "{table}" WHERE "{column}" IS NOT NULL'):
            value = record["value"]
            reference = json.loads(value) if isinstance(value, str) else value
            if reference is None:  # JSON null in an optional reference is absent.
                continue
            if not isinstance(reference, dict) or set(reference) != {"object_key", "sha256"}:
                raise ValueError("Malformed direct controlled object reference")
            result.append(reference)
    for row in await connection.fetch("SELECT details FROM audit_events WHERE action='V13_IMPORT_FILE_UPLOADED' ORDER BY id"):
        details = row["details"]
        details = json.loads(details) if isinstance(details, str) else details
        reference = details.get("raw_file_ref") if isinstance(details, dict) else None
        if not isinstance(reference, dict) or set(reference) != {"object_key", "sha256"}:
            raise ValueError("Malformed original upload reference")
        result.append(reference)
    return result
