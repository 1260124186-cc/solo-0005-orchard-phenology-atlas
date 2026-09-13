"""标量校验与规范化工具。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..errors import ValidationError


CODE_PATTERN = re.compile(r"^[A-Z]{2,6}-\d{3,4}$")
TREE_CODE_PATTERN = re.compile(r"^[A-Z]{2,6}-\d{3,4}-T\d{2,3}$")
SEASON_PATTERN = re.compile(r"^\d{4}$")


def require_object(value: Any, label: str = "请求体") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label}必须是 JSON 对象")
    return value


def reject_unknown_fields(
    payload: dict[str, Any],
    allowed: set[str],
    *,
    label: str,
) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValidationError(
            f"{label}包含不支持的字段",
            details={"unknown_fields": unknown},
        )


def clean_text(
    value: Any,
    field_name: str,
    *,
    minimum: int = 1,
    maximum: int = 120,
    required: bool = True,
) -> str:
    if value is None:
        if required:
            raise ValidationError("此字段为必填项", field_name=field_name)
        return ""
    if not isinstance(value, str):
        raise ValidationError("此字段必须是文本", field_name=field_name)
    normalized = " ".join(value.strip().split())
    if required and len(normalized) < minimum:
        raise ValidationError(
            f"至少需要 {minimum} 个字符",
            field_name=field_name,
        )
    if len(normalized) > maximum:
        raise ValidationError(
            f"最多允许 {maximum} 个字符",
            field_name=field_name,
            details={"actual_length": len(normalized)},
        )
    return normalized


def clean_plot_code(value: Any) -> str:
    code = clean_text(value, "code", minimum=6, maximum=11).upper()
    if not CODE_PATTERN.fullmatch(code):
        raise ValidationError(
            "园区编号格式应为两个到六个字母、连字符和三位或四位数字",
            field_name="code",
        )
    return code


def clean_tree_code(value: Any) -> str:
    code = clean_text(value, "code", minimum=10, maximum=17).upper()
    if not TREE_CODE_PATTERN.fullmatch(code):
        raise ValidationError(
            "植株编号应包含园区编号和 T 加两位或三位序号",
            field_name="code",
        )
    return code


def clean_season(value: Any) -> str:
    season = str(value or "").strip()
    if not SEASON_PATTERN.fullmatch(season):
        raise ValidationError(
            "季节年份必须是四位数字",
            field_name="season",
        )
    year = int(season)
    current_year = date.today().year
    if year < 1980 or year > current_year + 2:
        raise ValidationError(
            "季节年份超出当前档案允许范围",
            field_name="season",
            details={"minimum": 1980, "maximum": current_year + 2},
        )
    return season


def clean_year(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError("年份必须是整数", field_name=field_name)
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("年份必须是整数", field_name=field_name) from exc
    current_year = date.today().year
    if year < 1800 or year > current_year + 2:
        raise ValidationError(
            "年份超出允许范围",
            field_name=field_name,
            details={"minimum": 1800, "maximum": current_year + 2},
        )
    return year


def clean_confidence(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("置信度必须是 1 到 5 的整数", field_name="confidence")
    try:
        confidence = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "置信度必须是 1 到 5 的整数",
            field_name="confidence",
        ) from exc
    if confidence < 1 or confidence > 5:
        raise ValidationError(
            "置信度必须在 1 到 5 之间",
            field_name="confidence",
        )
    return confidence


def clean_date(value: Any, field_name: str) -> str:
    raw = clean_text(value, field_name, minimum=10, maximum=10)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(
            "日期必须使用 YYYY-MM-DD 格式",
            field_name=field_name,
        ) from exc
    return parsed.isoformat()


def clean_revision(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("修订号必须是整数", field_name="revision")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("修订号必须是整数", field_name="revision") from exc
    if revision < 1:
        raise ValidationError("修订号必须大于零", field_name="revision")
    return revision


def parse_boolean(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"true", "1", "yes"}:
            return True
        if value.lower() in {"false", "0", "no"}:
            return False
    raise ValidationError("此字段必须是布尔值", field_name=field_name)
