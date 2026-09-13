"""固定物候阶段定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..errors import ValidationError


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    label: str
    rank: int
    required_for_completion: bool


STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("bud_swell", "芽膨大期", 10, False),
    StageDefinition("bud_burst", "萌芽期", 20, True),
    StageDefinition("first_bloom", "初花期", 30, False),
    StageDefinition("full_bloom", "盛花期", 40, True),
    StageDefinition("petal_fall", "落瓣期", 50, False),
    StageDefinition("fruit_set", "坐果期", 60, True),
    StageDefinition("fruit_growth", "果实膨大期", 70, False),
    StageDefinition("harvest", "采收期", 80, True),
    StageDefinition("leaf_fall", "落叶期", 90, False),
)

STAGE_BY_KEY = {stage.key: stage for stage in STAGES}


def stage_definition(key: str) -> StageDefinition:
    normalized = str(key or "").strip().lower()
    try:
        return STAGE_BY_KEY[normalized]
    except KeyError as exc:
        raise ValidationError(
            "未知的物候阶段",
            field_name="stage",
            details={"stage": key, "allowed": list(STAGE_BY_KEY)},
        ) from exc


def sort_stage_entries(entries: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        entries,
        key=lambda item: (
            STAGE_BY_KEY.get(str(item.get("stage")), STAGES[-1]).rank,
            str(item.get("observed_on", "")),
        ),
    )


def required_stage_keys() -> set[str]:
    return {stage.key for stage in STAGES if stage.required_for_completion}


def stage_labels() -> dict[str, str]:
    return {stage.key: stage.label for stage in STAGES}
