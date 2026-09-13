"""编研简报用例。"""

from __future__ import annotations

from typing import Any

from ..domain.brief_rules import brief_summary, create_brief_record
from ..domain.plot_rules import now_iso
from ..errors import NotFoundError, ValidationError
from ..persistence import Repository


class BriefService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_briefs(self, *, plot_id: str | None = None) -> dict[str, Any]:
        state = self.repository.read()
        items = []
        for record in state["briefs"].values():
            if plot_id and record["plot"]["id"] != plot_id:
                continue
            items.append(brief_summary(record, include_payload=False))
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return {"items": items, "total": len(items)}

    def get_brief(self, brief_id: str) -> dict[str, Any]:
        state = self.repository.read()
        record = state["briefs"].get(brief_id)
        if record is None:
            raise NotFoundError("编研简报", brief_id)
        return brief_summary(record, include_payload=True)

    def create_brief(
        self,
        plot_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"title"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "生成简报包含不支持的字段",
                details={"unknown_fields": unknown},
            )

        def action(state: dict[str, Any]) -> dict[str, Any]:
            plot = state["plots"].get(plot_id)
            if plot is None:
                raise NotFoundError("园区", plot_id)
            trees = [
                tree
                for tree in state["trees"].values()
                if tree["plot_id"] == plot_id
            ]
            observations = [
                observation
                for observation in state["observations"].values()
                if observation["plot_id"] == plot_id
            ]
            record = create_brief_record(
                payload,
                plot,
                trees,
                observations,
                int(state["revision"]) + 1,
                now_iso(),
            )
            state["briefs"][record["id"]] = record
            return record

        record = self.repository.atomic_update(action)
        return brief_summary(record, include_payload=True)
