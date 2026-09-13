"""季节志对齐用例。"""

from __future__ import annotations

from typing import Any

from ..domain.comparison_rules import (
    comparison_summary,
    create_comparison_record,
)
from ..domain.plot_rules import now_iso
from ..errors import NotFoundError, ValidationError
from ..persistence import Repository


class ComparisonService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_comparisons(self) -> dict[str, Any]:
        state = self.repository.read()
        items = [
            comparison_summary(record)
            for record in state["comparisons"].values()
        ]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return {"items": items, "total": len(items)}

    def get_comparison(self, comparison_id: str) -> dict[str, Any]:
        state = self.repository.read()
        record = state["comparisons"].get(comparison_id)
        if record is None:
            raise NotFoundError("对比图谱", comparison_id)
        return comparison_summary(record)

    def create_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "left_observation_id",
            "right_observation_id",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "生成对比图谱包含不支持的字段",
                details={"unknown_fields": unknown},
            )

        def action(state: dict[str, Any]) -> dict[str, Any]:
            left_id = str(payload.get("left_observation_id") or "")
            right_id = str(payload.get("right_observation_id") or "")
            left = state["observations"].get(left_id)
            if left is None:
                raise NotFoundError("左侧季节志", left_id)
            right = state["observations"].get(right_id)
            if right is None:
                raise NotFoundError("右侧季节志", right_id)
            left_tree = state["trees"].get(left["tree_id"])
            right_tree = state["trees"].get(right["tree_id"])
            record = create_comparison_record(
                payload,
                left,
                right,
                left_tree,
                right_tree,
                now_iso(),
            )
            duplicate = self._find_duplicate(
                state["comparisons"],
                record["left_observation_id"],
                record["right_observation_id"],
            )
            if duplicate is not None:
                return duplicate
            state["comparisons"][record["id"]] = record
            return record

        record = self.repository.atomic_update(action)
        return comparison_summary(record)

    @staticmethod
    def _find_duplicate(
        comparisons: dict[str, dict[str, Any]],
        left_id: str,
        right_id: str,
    ) -> dict[str, Any] | None:
        for record in comparisons.values():
            pair = {record["left_observation_id"], record["right_observation_id"]}
            if pair == {left_id, right_id}:
                return record
        return None
