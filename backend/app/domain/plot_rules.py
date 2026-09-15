"""园区与植株实体规则。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..errors import ConflictError, PreconditionError, ValidationError
from .value_checks import (
    clean_plot_code,
    clean_text,
    clean_tree_code,
    clean_year,
    reject_unknown_fields,
)


PLOT_FIELDS = {
    "code",
    "name",
    "locality",
    "cultivar_focus",
    "steward",
    "planting_year",
    "note",
}
TREE_FIELDS = {
    "plot_id",
    "code",
    "cultivar",
    "rootstock",
    "planting_year",
    "status",
    "note",
}
TREE_STATUSES = {"active", "retired", "lost"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_plot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(payload, PLOT_FIELDS, label="园区信息")
    planting_year = clean_year(payload.get("planting_year"), "planting_year")
    return {
        "code": clean_plot_code(payload.get("code")),
        "name": clean_text(payload.get("name"), "name", maximum=80),
        "locality": clean_text(payload.get("locality"), "locality", maximum=160),
        "cultivar_focus": clean_text(
            payload.get("cultivar_focus"),
            "cultivar_focus",
            maximum=80,
        ),
        "steward": clean_text(payload.get("steward"), "steward", maximum=80),
        "planting_year": planting_year,
        "note": clean_text(
            payload.get("note", ""),
            "note",
            maximum=500,
            required=False,
        ),
    }


def create_plot_record(payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    normalized = normalize_plot_payload(payload)
    return {
        "id": new_identifier("plot"),
        "schema_version": 1,
        **normalized,
        "status": "draft",
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "confirmed_at": None,
    }


def ensure_unique_plot_code(
    plots: dict[str, dict[str, Any]],
    code: str,
    *,
    excluded_id: str | None = None,
) -> None:
    for plot in plots.values():
        if plot["code"] == code and plot["id"] != excluded_id:
            raise ConflictError(
                "plot_code_exists",
                "园区编号已存在",
                plot_code=code,
            )


def update_plot_record(
    plot: dict[str, Any],
    payload: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    if plot["status"] != "draft":
        raise PreconditionError(
            "plot_not_editable",
            "已确认园区不能直接修改",
        )
    if expected_revision is not None:
        verify_revision(plot, expected_revision)
    merged = {
        "code": payload.get("code", plot["code"]),
        "name": payload.get("name", plot["name"]),
        "locality": payload.get("locality", plot["locality"]),
        "cultivar_focus": payload.get(
            "cultivar_focus",
            plot["cultivar_focus"],
        ),
        "steward": payload.get("steward", plot["steward"]),
        "planting_year": payload.get("planting_year", plot["planting_year"]),
        "note": payload.get("note", plot["note"]),
    }
    normalized = normalize_plot_payload(merged)
    return {
        **plot,
        **normalized,
        "revision": int(plot["revision"]) + 1,
        "updated_at": now_iso(),
    }


def confirm_plot_record(
    plot: dict[str, Any],
    trees: dict[str, dict[str, Any]],
    *,
    expected_revision: int | None,
) -> dict[str, Any]:
    if plot["status"] != "draft":
        raise PreconditionError("plot_already_confirmed", "园区已经确认")
    if expected_revision is not None:
        verify_revision(plot, expected_revision)
    active_trees = [
        item
        for item in trees.values()
        if item["plot_id"] == plot["id"] and item["status"] == "active"
    ]
    if not active_trees:
        raise PreconditionError(
            "plot_requires_tree",
            "确认前至少需要一株在册植株",
        )
    timestamp = now_iso()
    return {
        **plot,
        "status": "confirmed",
        "revision": int(plot["revision"]) + 1,
        "updated_at": timestamp,
        "confirmed_at": timestamp,
    }


def normalize_tree_payload(
    payload: dict[str, Any],
    *,
    allow_status: bool,
) -> dict[str, Any]:
    reject_unknown_fields(payload, TREE_FIELDS, label="植株信息")
    status = str(payload.get("status", "active")).strip().lower()
    if not allow_status and status != "active":
        raise ValidationError("新植株状态必须是 active", field_name="status")
    if status not in TREE_STATUSES:
        raise ValidationError(
            "植株状态不合法",
            field_name="status",
            details={"allowed": sorted(TREE_STATUSES)},
        )
    return {
        "plot_id": clean_text(
            payload.get("plot_id"),
            "plot_id",
            minimum=5,
            maximum=40,
        ),
        "code": clean_tree_code(payload.get("code")),
        "cultivar": clean_text(payload.get("cultivar"), "cultivar", maximum=80),
        "rootstock": clean_text(
            payload.get("rootstock", "未记录"),
            "rootstock",
            maximum=80,
            required=False,
        )
        or "未记录",
        "planting_year": clean_year(payload.get("planting_year"), "planting_year"),
        "status": status,
        "note": clean_text(
            payload.get("note", ""),
            "note",
            maximum=500,
            required=False,
        ),
    }


def create_tree_record(
    payload: dict[str, Any],
    plot: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    normalized = normalize_tree_payload(payload, allow_status=False)
    if normalized["plot_id"] != plot["id"]:
        raise ValidationError("植株所属园区不匹配", field_name="plot_id")
    if plot["status"] != "draft":
        raise PreconditionError(
            "plot_not_editable",
            "只能向草稿园区添加植株",
        )
    if normalized["planting_year"] < int(plot["planting_year"]):
        raise ValidationError(
            "植株定植年份不能早于园区起始种植年份",
            field_name="planting_year",
        )
    return {
        "id": new_identifier("tree"),
        "schema_version": 1,
        **normalized,
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def ensure_unique_tree_code(
    trees: dict[str, dict[str, Any]],
    plot_id: str,
    code: str,
    *,
    excluded_id: str | None = None,
) -> None:
    for tree in trees.values():
        if (
            tree["plot_id"] == plot_id
            and tree["code"] == code
            and tree["id"] != excluded_id
        ):
            raise ConflictError(
                "tree_code_exists",
                "该园区内植株编号已存在",
                tree_code=code,
            )


def ensure_tree_belongs_to_plot(
    tree: dict[str, Any] | None,
    plot_id: str,
) -> dict[str, Any]:
    if tree is None or tree["plot_id"] != plot_id:
        raise ValidationError("园区内不存在该植株", field_name="tree_id")
    return tree


def retire_tree_record(
    tree: dict[str, Any],
    *,
    status: str,
    note: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    verify_revision(tree, expected_revision)
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"retired", "lost"}:
        raise ValidationError(
            "结束状态只能是 retired 或 lost",
            field_name="status",
        )
    if tree["status"] != "active":
        raise PreconditionError("tree_already_closed", "植株已经结束在册状态")
    return {
        **tree,
        "status": normalized_status,
        "note": clean_text(
            note if note is not None else tree["note"],
            "note",
            maximum=500,
            required=False,
        ),
        "revision": int(tree["revision"]) + 1,
        "updated_at": now_iso(),
    }


def verify_revision(
    record: dict[str, Any],
    expected_revision: Any,
) -> None:
    if isinstance(expected_revision, bool):
        raise ValidationError("修订号必须是整数", field_name="revision")
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise ValidationError("修订号必须是整数", field_name="revision") from exc
    actual = int(record.get("revision", 0))
    if expected != actual:
        raise ConflictError(
            "revision_conflict",
            "记录已被其他请求修改，请重新读取",
            expected=expected,
            actual=actual,
        )


def plot_summary(plot: dict[str, Any], tree_count: int) -> dict[str, Any]:
    return {
        "id": plot["id"],
        "code": plot["code"],
        "name": plot["name"],
        "locality": plot["locality"],
        "cultivar_focus": plot["cultivar_focus"],
        "steward": plot["steward"],
        "planting_year": plot["planting_year"],
        "note": plot["note"],
        "status": plot["status"],
        "revision": plot["revision"],
        "created_at": plot["created_at"],
        "updated_at": plot["updated_at"],
        "confirmed_at": plot["confirmed_at"],
        "tree_count": tree_count,
    }
