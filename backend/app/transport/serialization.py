"""稳定的公开数据视图。"""

from __future__ import annotations

from typing import Any


def envelope(
    payload: Any,
    *,
    state_revision: int | None = None,
) -> dict[str, Any]:
    result = {"data": payload}
    if state_revision is not None:
        result["state_revision"] = state_revision
    return result


def error_envelope(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
