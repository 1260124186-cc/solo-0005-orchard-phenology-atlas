"""任务排队、租约、重试和死信管理。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..errors import ConflictError, NotFoundError, PreconditionError, ValidationError
from ..persistence.database import Database


JOB_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
}


class JobService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def enqueue(
        self,
        *,
        actor_id: str,
        job_type: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        priority: int = 100,
        available_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        normalized_type = str(job_type or "").strip()
        if not normalized_type:
            raise ValidationError("任务类型不能为空", field_name="job_type")
        if not isinstance(payload, dict):
            raise ValidationError("任务载荷必须是 JSON 对象", field_name="payload")
        if max_attempts < 1 or max_attempts > 20:
            raise ValidationError(
                "最大尝试次数必须在 1 到 20 之间",
                field_name="max_attempts",
            )
        if priority < 0 or priority > 10_000:
            raise ValidationError(
                "任务优先级必须在 0 到 10000 之间",
                field_name="priority",
            )
        timestamp = _now()
        available = available_at or timestamp
        identifier = _job_identifier(actor_id, idempotency_key)
        with self.database.transaction(immediate=True) as connection:
            if idempotency_key:
                existing = _fetch_job(connection, identifier)
                if existing is not None:
                    if (
                        existing["job_type"] != normalized_type
                        or json.loads(existing["payload"]) != payload
                    ):
                        raise ConflictError(
                            "job_idempotency_conflict",
                            "同一幂等键已用于不同任务",
                            idempotency_key=idempotency_key,
                        )
                    return _job_view(existing)
            connection.execute(
                """
                INSERT INTO jobs
                (id, job_type, payload, status, attempt, max_attempts,
                 priority, available_at, created_by, created_at)
                VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    normalized_type,
                    _json(payload),
                    max_attempts,
                    priority,
                    available,
                    actor_id,
                    timestamp,
                ),
            )
            row = _fetch_job(connection, identifier)
        if row is None:
            raise ConflictError("job_create_failed", "任务创建失败")
        return _job_view(row)

    def list_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if status and status not in JOB_STATUSES:
            raise ValidationError("任务状态不合法", field_name="status")
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if job_type:
            clauses.append("job_type = ?")
            params.append(job_type)
        if actor_id:
            clauses.append("created_by = ?")
            params.append(actor_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.database.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM jobs
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return {"items": [_job_view(row) for row in rows], "total": len(rows)}

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            row = _fetch_job(connection, job_id)
        if row is None:
            raise NotFoundError("后台任务", job_id)
        return _job_view(row)

    def cancel(self, job_id: str, *, actor_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = _fetch_job(connection, job_id)
            if row is None:
                raise NotFoundError("后台任务", job_id)
            if row["status"] not in {"queued", "failed"}:
                raise PreconditionError(
                    "job_not_cancellable",
                    "只有排队或失败任务可以取消",
                    status=row["status"],
                )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', finished_at = ?, lease_expires_at = NULL,
                    worker_id = NULL, error = ?
                WHERE id = ?
                """,
                (_now(), f"由 {actor_id} 取消", job_id),
            )
            updated = _fetch_job(connection, job_id)
        return _job_view(updated)

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any] | None:
        timestamp = _now()
        lease_until = _future(lease_seconds)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', worker_id = NULL, lease_expires_at = NULL,
                    error = COALESCE(error, '租约过期，已重新排队')
                WHERE status = 'running' AND lease_expires_at < ?
                """,
                (timestamp,),
            )
            row = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status = 'queued' AND available_at <= ?
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
                (timestamp,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempt = attempt + 1,
                    worker_id = ?,
                    lease_expires_at = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL
                WHERE id = ?
                """,
                (worker_id, lease_until, timestamp, row["id"]),
            )
            claimed = _fetch_job(connection, row["id"])
        return _job_view(claimed)

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = _require_running_job(connection, job_id, worker_id)
            connection.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE id = ?",
                (_future(lease_seconds), row["id"]),
            )
            updated = _fetch_job(connection, job_id)
        return _job_view(updated)

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = _require_running_job(connection, job_id, worker_id)
            connection.execute(
                """
                UPDATE jobs
                SET status = 'succeeded', result = ?, error = NULL,
                    lease_expires_at = NULL, worker_id = NULL, finished_at = ?
                WHERE id = ?
                """,
                (_json(result or {}), _now(), row["id"]),
            )
            updated = _fetch_job(connection, job_id)
        return _job_view(updated)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = _require_running_job(connection, job_id, worker_id)
            terminal = int(row["attempt"]) >= int(row["max_attempts"])
            if terminal:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'dead_letter', error = ?,
                        lease_expires_at = NULL, worker_id = NULL, finished_at = ?
                    WHERE id = ?
                    """,
                    (error[:4000], _now(), row["id"]),
                )
            else:
                delay = retry_delay_seconds
                if delay is None:
                    delay = min(300, 2 ** int(row["attempt"]))
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', error = ?, available_at = ?,
                        lease_expires_at = NULL, worker_id = NULL, finished_at = ?
                    WHERE id = ?
                    """,
                    (error[:4000], _future(delay), _now(), row["id"]),
                )
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'queued'
                    WHERE id = ? AND status = 'failed'
                    """,
                    (row["id"],),
                )
            updated = _fetch_job(connection, job_id)
        return _job_view(updated)

    def retry(self, job_id: str, *, actor_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = _fetch_job(connection, job_id)
            if row is None:
                raise NotFoundError("后台任务", job_id)
            if row["status"] not in {"failed", "dead_letter", "cancelled"}:
                raise PreconditionError(
                    "job_not_retryable",
                    "只有失败、死信或取消任务可以重试",
                    status=row["status"],
                )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', attempt = 0, available_at = ?,
                    error = NULL, result = NULL, finished_at = NULL,
                    worker_id = NULL, lease_expires_at = NULL
                WHERE id = ?
                """,
                (_now(), job_id),
            )
            updated = _fetch_job(connection, job_id)
        return _job_view(updated)


def _require_running_job(
    connection: sqlite3.Connection,
    job_id: str,
    worker_id: str,
) -> sqlite3.Row:
    row = _fetch_job(connection, job_id)
    if row is None:
        raise NotFoundError("后台任务", job_id)
    if row["status"] != "running" or row["worker_id"] != worker_id:
        raise PreconditionError(
            "job_lease_invalid",
            "任务租约不属于当前 worker",
            status=row["status"],
        )
    return row


def _fetch_job(
    connection: sqlite3.Connection,
    job_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()


def _job_view(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        raise RuntimeError("job row is missing")
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "payload": json.loads(row["payload"]),
        "status": row["status"],
        "attempt": row["attempt"],
        "max_attempts": row["max_attempts"],
        "priority": row["priority"],
        "available_at": row["available_at"],
        "lease_expires_at": row["lease_expires_at"],
        "worker_id": row["worker_id"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _job_identifier(actor_id: str, idempotency_key: str | None) -> str:
    if not idempotency_key:
        return f"job_{uuid.uuid4().hex}"
    digest = hashlib.sha256(
        f"{actor_id}\0{idempotency_key}".encode("utf-8")
    ).hexdigest()[:24]
    return f"job_{digest}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _future(seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))
    ).replace(microsecond=0).isoformat()
