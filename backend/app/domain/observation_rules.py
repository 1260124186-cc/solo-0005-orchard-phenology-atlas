"""季节志与物候条目规则。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..errors import ConflictError, PreconditionError, ValidationError
from .plot_rules import new_identifier, now_iso, verify_revision
from .stages import STAGE_BY_KEY, required_stage_keys, sort_stage_entries, stage_definition
from .value_checks import (
    clean_confidence,
    clean_date,
    clean_season,
    clean_text,
    reject_unknown_fields,
)


START_FIELDS = {"tree_id", "season", "observer", "note"}
STAGE_FIELDS = {"stage", "observed_on", "confidence", "note"}
COMPLETE_FIELDS = {"revision"}


def create_observation_record(
    payload: dict[str, Any],
    tree: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    reject_unknown_fields(payload, START_FIELDS, label="季节志信息")
    tree_id = clean_text(
        payload.get("tree_id"),
        "tree_id",
        minimum=5,
        maximum=40,
    )
    if tree_id != tree["id"]:
        raise ValidationError("季节志植株标识不匹配", field_name="tree_id")
    if tree["status"] != "active":
        raise PreconditionError(
            "tree_not_active",
            "只能为在册植株建立季节志",
        )
    return {
        "id": new_identifier("season"),
        "schema_version": 1,
        "tree_id": tree_id,
        "plot_id": tree["plot_id"],
        "season": clean_season(payload.get("season")),
        "observer": clean_text(
            payload.get("observer"),
            "observer",
            maximum=80,
        ),
        "note": clean_text(
            payload.get("note", ""),
            "note",
            maximum=500,
            required=False,
        ),
        "status": "open",
        "entries": [],
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
    }


def ensure_unique_open_observation(
    observations: dict[str, dict[str, Any]],
    tree_id: str,
    season: str,
    *,
    excluded_id: str | None = None,
) -> None:
    for observation in observations.values():
        if (
            observation["tree_id"] == tree_id
            and observation["season"] == season
            and observation["id"] != excluded_id
        ):
            raise ConflictError(
                "season_exists",
                "该植株在这一季节已有记录",
                existing_id=observation["id"],
                status=observation["status"],
            )


def add_stage_entry(
    observation: dict[str, Any],
    payload: dict[str, Any],
    *,
    expected_revision: int,
) -> dict[str, Any]:
    reject_unknown_fields(payload, STAGE_FIELDS, label="物候条目")
    ensure_observation_open(observation)
    verify_revision(observation, expected_revision)
    definition = stage_definition(str(payload.get("stage", "")))
    observed_on = clean_date(payload.get("observed_on"), "observed_on")
    validate_date_window(observed_on, observation["season"])
    confidence = clean_confidence(payload.get("confidence"))
    note = clean_text(
        payload.get("note", ""),
        "note",
        maximum=300,
        required=False,
    )
    existing = observation.get("entries", [])
    if any(item["stage"] == definition.key for item in existing):
        raise ConflictError(
            "stage_exists",
            "该阶段已经记录，请先移除原条目",
            stage=definition.key,
        )
    candidate_entries = [
        *existing,
        {
            "id": new_identifier("entry"),
            "stage": definition.key,
            "observed_on": observed_on,
            "confidence": confidence,
            "note": note,
            "created_at": now_iso(),
        },
    ]
    validate_stage_sequence(candidate_entries)
    return {
        **observation,
        "entries": sort_stage_entries(candidate_entries),
        "revision": int(observation["revision"]) + 1,
        "updated_at": now_iso(),
    }


def remove_stage_entry(
    observation: dict[str, Any],
    stage: str,
    *,
    expected_revision: int,
) -> dict[str, Any]:
    ensure_observation_open(observation)
    verify_revision(observation, expected_revision)
    definition = stage_definition(stage)
    entries = observation.get("entries", [])
    remaining = [item for item in entries if item["stage"] != definition.key]
    if len(remaining) == len(entries):
        raise ValidationError("季节志中没有该阶段", field_name="stage")
    return {
        **observation,
        "entries": sort_stage_entries(remaining),
        "revision": int(observation["revision"]) + 1,
        "updated_at": now_iso(),
    }


def complete_observation_record(
    observation: dict[str, Any],
    *,
    expected_revision: int,
) -> dict[str, Any]:
    ensure_observation_open(observation)
    verify_revision(observation, expected_revision)
    entries = observation.get("entries", [])
    present = {item["stage"] for item in entries}
    missing = sorted(
        required_stage_keys() - present,
        key=lambda key: STAGE_BY_KEY[key].rank,
    )
    if missing:
        labels = [STAGE_BY_KEY[key].label for key in missing]
        raise PreconditionError(
            "required_stages_missing",
            "缺少完成季节志所需的阶段",
            missing=missing,
            labels=labels,
        )
    validate_stage_sequence(entries)
    timestamp = now_iso()
    return {
        **observation,
        "entries": sort_stage_entries(entries),
        "status": "completed",
        "revision": int(observation["revision"]) + 1,
        "updated_at": timestamp,
        "completed_at": timestamp,
    }


def ensure_observation_open(observation: dict[str, Any]) -> None:
    if observation["status"] != "open":
        raise PreconditionError(
            "season_not_editable",
            "已完成的季节志不可修改",
        )


def validate_date_window(observed_on: str, season: str) -> None:
    season_year = int(season)
    observed = date.fromisoformat(observed_on)
    start = date(season_year, 1, 1) - timedelta(days=90)
    end = date(season_year, 12, 31) + timedelta(days=90)
    if observed < start or observed > end:
        raise ValidationError(
            "观察日期超出该季节允许窗口",
            field_name="observed_on",
            details={
                "minimum": start.isoformat(),
                "maximum": end.isoformat(),
            },
        )


def validate_stage_sequence(entries: list[dict[str, Any]]) -> None:
    ordered = sort_stage_entries(entries)
    previous_rank = -1
    previous_date: date | None = None
    previous_label = ""
    for entry in ordered:
        definition = stage_definition(str(entry.get("stage", "")))
        observed = date.fromisoformat(clean_date(entry.get("observed_on"), "observed_on"))
        if definition.rank < previous_rank:
            raise ValidationError(
                "物候阶段顺序不合法",
                details={"previous": previous_label, "current": definition.label},
            )
        if previous_date is not None and observed < previous_date:
            raise ValidationError(
                "后一物候阶段的日期不能早于前一阶段",
                details={
                    "previous": previous_label,
                    "previous_date": previous_date.isoformat(),
                    "current": definition.label,
                    "current_date": observed.isoformat(),
                },
            )
        previous_rank = definition.rank
        previous_date = observed
        previous_label = definition.label


def observation_summary(
    observation: dict[str, Any],
    tree: dict[str, Any] | None,
) -> dict[str, Any]:
    entries = sort_stage_entries(observation.get("entries", []))
    return {
        "id": observation["id"],
        "tree_id": observation["tree_id"],
        "plot_id": observation["plot_id"],
        "tree_code": tree["code"] if tree else "已移除",
        "cultivar": tree["cultivar"] if tree else "未知品种",
        "season": observation["season"],
        "observer": observation["observer"],
        "note": observation["note"],
        "status": observation["status"],
        "revision": observation["revision"],
        "created_at": observation["created_at"],
        "updated_at": observation["updated_at"],
        "completed_at": observation["completed_at"],
        "stage_count": len(entries),
        "entry_map": {
            item["stage"]: {
                "observed_on": item["observed_on"],
                "confidence": item["confidence"],
                "note": item["note"],
            }
            for item in entries
        },
        "entries": entries,
    }


def update_observation_note(
    observation: dict[str, Any],
    *,
    note: str,
    expected_revision: int,
) -> dict[str, Any]:
    ensure_observation_open(observation)
    verify_revision(observation, expected_revision)
    return {
        **observation,
        "note": clean_text(note, "note", maximum=500, required=False),
        "revision": int(observation["revision"]) + 1,
        "updated_at": now_iso(),
    }
