"""领域错误与统一错误分类。"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code: str
    message: str
    status: int
    details: dict[str, Any]

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = dict(details or {})

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ValidationError(DomainError):
    def __init__(
        self,
        message: str,
        *,
        field_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(details or {})
        if field_name is not None:
            payload["field"] = field_name
        super().__init__("validation_error", message, 422, payload)


class NotFoundError(DomainError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            "not_found",
            f"未找到{resource}：{identifier}",
            404,
            {"resource": resource, "id": identifier},
        )


class ConflictError(DomainError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code, message, 409, details)


class PreconditionError(DomainError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code, message, 412, details)
