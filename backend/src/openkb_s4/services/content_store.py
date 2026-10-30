"""Content-addressed private files: atomically seal first, publish DB refs second.

References are deliberately opaque to HTTP clients. Orphaned objects survive a
failed transaction; reconciliation must never delete sealed material implicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


class ContentStoreError(ValueError):
    """Safe error without file content or externally supplied paths."""


class ContentStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @staticmethod
    def _encode(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")

    def _path(self, reference: dict[str, Any]) -> Path:
        digest = reference.get("sha256")
        key = reference.get("object_key")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContentStoreError("Invalid controlled object digest")
        expected = f"objects/{digest[:2]}/{digest}.json"
        if key != expected:
            raise ContentStoreError("Invalid controlled object reference")
        path = self.root / expected
        if not path.resolve().is_relative_to(self.root):
            raise ContentStoreError("Controlled object escapes its root")
        # Reject symlink components even if a link points back inside the root.
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != self.root.parent):
            raise ContentStoreError("Controlled object cannot use a symlink")
        return path

    def put_json(self, value: Any) -> dict[str, str]:
        data = self._encode(value)
        digest = hashlib.sha256(data).hexdigest()
        ref = {"object_key": f"objects/{digest[:2]}/{digest}.json", "sha256": digest}
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.read_json(ref)
            return ref
        temporary = path.with_name(f".{digest}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Linking is atomic and won't overwrite another publisher's object.
            try:
                os.link(temporary, path)
            except FileExistsError:
                self.read_json(ref)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
        self.read_json(ref)
        return ref

    def validate_reference(self, reference: dict[str, Any]) -> None:
        if not isinstance(reference, dict) or set(reference) != {"object_key", "sha256"}:
            raise ContentStoreError("Invalid controlled object reference shape")
        self._path(reference)

    def read_json(self, reference: dict[str, Any]) -> Any:
        path = self._path(reference)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ContentStoreError("Controlled object is missing or unreadable") from exc
        if hashlib.sha256(data).hexdigest() != reference["sha256"]:
            raise ContentStoreError("Controlled object digest mismatch")
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ContentStoreError("Controlled object JSON is invalid") from exc

    def inventory(self) -> list[dict[str, str]]:
        records = []
        for path in sorted((self.root / "objects").glob("*/*.json")):
            ref = {"object_key": path.relative_to(self.root).as_posix(), "sha256": path.stem}
            self.read_json(ref)
            records.append(ref)
        return records

    def verify_references(self, references: list[dict[str, Any]]) -> int:
        for reference in references:
            self.read_json(reference)
        return len(references)
