"""Transactional durable job/outbox registration and business-key deduplication."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Job


async def enqueue(db: AsyncSession, kind: str, business_key: str, creator_id: str,
                  payload: dict[str, Any]) -> Job:
    """Register once in the caller's transaction; a worker executes after commit."""
    # A select-then-insert race would return 409 to an otherwise identical retry.
    await db.execute(insert(Job).values(kind=kind, business_key=business_key,
                                       creator_id=creator_id, payload=payload).on_conflict_do_nothing(index_elements=[Job.business_key]))
    job = await db.scalar(select(Job).where(Job.business_key == business_key).with_for_update())
    assert job is not None
    if job.state == "FAILED":
        job.state, job.attempts = "PENDING", 0
        job.error_code, job.error_message, job.lease_until = None, None, None
    return job
