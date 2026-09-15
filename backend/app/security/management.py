"""本机操作者与授权范围管理。"""

from __future__ import annotations

import uuid
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..errors import ConflictError, NotFoundError, ValidationError
from ..persistence.database import Database
from .context import current_request_context


class IdentityService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_actors(self) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, display_name, status, created_at
                FROM actors
                ORDER BY created_at, id
                """
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}

    def create_actor(
        self,
        *,
        actor_id: str,
        display_name: str,
        status: str = "active",
    ) -> dict[str, Any]:
        normalized_id = _required_text(actor_id, "id", 3, 80)
        normalized_name = _required_text(display_name, "display_name", 1, 80)
        if status not in {"active", "disabled"}:
            raise ValidationError("操作者状态不合法", field_name="status")
        timestamp = _now()
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT id FROM actors WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if existing is not None:
                raise ConflictError(
                    "actor_exists",
                    "操作者标识已存在",
                    actor_id=normalized_id,
                )
            connection.execute(
                """
                INSERT INTO actors (id, display_name, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (normalized_id, normalized_name, status, timestamp),
            )
            _record_security_event(
                connection,
                action="actor.create",
                resource_kind="actor",
                resource_id=normalized_id,
                details={"display_name": normalized_name, "status": status},
            )
        return {
            "id": normalized_id,
            "display_name": normalized_name,
            "status": status,
            "created_at": timestamp,
        }

    def list_grants(self, *, actor_id: str | None = None) -> dict[str, Any]:
        params: list[Any] = []
        where = ""
        if actor_id:
            where = "WHERE actor_id = ?"
            params.append(actor_id)
        with self.database.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, actor_id, capability, resource_kind, resource_id,
                       expires_at, revoked_at, created_at
                FROM access_grants
                {where}
                ORDER BY created_at, id
                """,
                params,
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}

    def grant(
        self,
        *,
        actor_id: str,
        capability: str,
        resource_kind: str,
        resource_id: str = "*",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_actor = _required_text(actor_id, "actor_id", 3, 80)
        normalized_capability = _required_text(capability, "capability", 1, 80)
        normalized_kind = _required_text(resource_kind, "resource_kind", 1, 80)
        normalized_resource = _required_text(resource_id or "*", "resource_id", 1, 120)
        if expires_at and not _valid_timestamp(expires_at):
            raise ValidationError(
                "授权到期时间必须是 ISO 8601",
                field_name="expires_at",
            )
        identifier = f"grant_{uuid.uuid4().hex[:16]}"
        timestamp = _now()
        with self.database.transaction(immediate=True) as connection:
            actor = connection.execute(
                "SELECT status FROM actors WHERE id = ?",
                (normalized_actor,),
            ).fetchone()
            if actor is None:
                raise NotFoundError("操作者", normalized_actor)
            duplicate = connection.execute(
                """
                SELECT id FROM access_grants
                WHERE actor_id = ? AND capability = ? AND resource_kind = ?
                  AND resource_id = ? AND revoked_at IS NULL
                """,
                (
                    normalized_actor,
                    normalized_capability,
                    normalized_kind,
                    normalized_resource,
                ),
            ).fetchone()
            if duplicate is not None:
                raise ConflictError(
                    "grant_exists",
                    "相同授权已经存在",
                    grant_id=duplicate["id"],
                )
            connection.execute(
                """
                INSERT INTO access_grants
                (id, actor_id, capability, resource_kind, resource_id,
                 expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    normalized_actor,
                    normalized_capability,
                    normalized_kind,
                    normalized_resource,
                    expires_at,
                    timestamp,
                ),
            )
            _record_security_event(
                connection,
                action="grant.create",
                resource_kind="grant",
                resource_id=identifier,
                details={
                    "actor_id": normalized_actor,
                    "capability": normalized_capability,
                    "resource_kind": normalized_kind,
                    "resource_id": normalized_resource,
                    "expires_at": expires_at,
                },
            )
        return {
            "id": identifier,
            "actor_id": normalized_actor,
            "capability": normalized_capability,
            "resource_kind": normalized_kind,
            "resource_id": normalized_resource,
            "expires_at": expires_at,
            "revoked_at": None,
            "created_at": timestamp,
        }

    def revoke(self, grant_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM access_grants WHERE id = ?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("授权", grant_id)
            if row["revoked_at"] is not None:
                raise ConflictError(
                    "grant_already_revoked",
                    "授权已经撤销",
                    grant_id=grant_id,
                )
            revoked_at = _now()
            connection.execute(
                "UPDATE access_grants SET revoked_at = ? WHERE id = ?",
                (revoked_at, grant_id),
            )
            _record_security_event(
                connection,
                action="grant.revoke",
                resource_kind="grant",
                resource_id=grant_id,
                details={
                    "actor_id": row["actor_id"],
                    "capability": row["capability"],
                    "resource_kind": row["resource_kind"],
                    "resource_id": row["resource_id"],
                    "revoked_at": revoked_at,
                },
            )
        return {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "capability": row["capability"],
            "resource_kind": row["resource_kind"],
            "resource_id": row["resource_id"],
            "expires_at": row["expires_at"],
            "revoked_at": revoked_at,
            "created_at": row["created_at"],
        }


def _required_text(
    value: Any,
    field_name: str,
    minimum: int,
    maximum: int,
) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < minimum:
        raise ValidationError(
            f"至少需要 {minimum} 个字符",
            field_name=field_name,
        )
    if len(normalized) > maximum:
        raise ValidationError(
            f"最多允许 {maximum} 个字符",
            field_name=field_name,
        )
    return normalized


def _valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_security_event(
    connection: sqlite3.Connection,
    *,
    action: str,
    resource_kind: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    context = current_request_context()
    actor_id = context.actor_id or "anonymous"
    timestamp = _now()
    event_id = f"evt_{uuid.uuid4().hex}"
    connection.execute(
        """
        INSERT INTO audit_events
        (event_id, actor_id, action, resource_kind, resource_id,
         revision, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            actor_id,
            action,
            resource_kind,
            resource_id,
            _revision(connection) + 1,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO outbox_events
        (event_id, topic, payload, status, attempts, created_at)
        VALUES (?, ?, ?, 'pending', 0, ?)
        """,
        (
            f"out_{uuid.uuid4().hex}",
            f"atlas.{resource_kind}.changed",
            json.dumps(
                {
                    "kind": resource_kind,
                    "id": resource_id,
                    "action": action,
                    "actor_id": actor_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            timestamp,
        ),
    )
    revision = _revision(connection) + 1
    connection.execute(
        """
        INSERT INTO meta (key, value) VALUES ('state_revision', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(revision),),
    )


def _revision(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'state_revision'"
    ).fetchone()
    return int(row["value"]) if row is not None else 0
