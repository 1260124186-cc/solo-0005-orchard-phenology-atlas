"""园区与植株用例。"""

from __future__ import annotations

from typing import Any

from ..domain.plot_rules import (
    confirm_plot_record,
    create_plot_record,
    create_tree_record,
    ensure_unique_plot_code,
    ensure_unique_tree_code,
    normalize_plot_payload,
    now_iso,
    plot_summary,
    retire_tree_record,
    update_plot_record,
)
from ..errors import NotFoundError, ValidationError
from ..persistence import Repository


PLOT_UPDATE_FIELDS = {
    "code",
    "name",
    "locality",
    "cultivar_focus",
    "steward",
    "planting_year",
    "note",
    "revision",
}


class CatalogService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_plots(
        self,
        *,
        status: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        state = self.repository.read()
        normalized_query = (query or "").strip().lower()
        plots: list[dict[str, Any]] = []
        for plot in state["plots"].values():
            if status and plot["status"] != status:
                continue
            haystack = " ".join(
                [
                    plot["code"],
                    plot["name"],
                    plot["locality"],
                    plot["cultivar_focus"],
                    plot["steward"],
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            tree_count = sum(
                1
                for tree in state["trees"].values()
                if tree["plot_id"] == plot["id"]
            )
            plots.append(plot_summary(plot, tree_count))
        plots.sort(key=lambda item: (item["status"] != "draft", item["code"]))
        return {"items": plots, "total": len(plots), "state_revision": state["revision"]}

    def get_plot(self, plot_id: str) -> dict[str, Any]:
        state = self.repository.read()
        return self._plot_detail(state, plot_id)

    def create_plot(self, payload: dict[str, Any]) -> dict[str, Any]:
        def action(state: dict[str, Any]) -> dict[str, Any]:
            normalized = normalize_plot_payload(payload)
            ensure_unique_plot_code(state["plots"], normalized["code"])
            record = create_plot_record(payload, now_iso())
            state["plots"][record["id"]] = record
            return record

        record = self.repository.atomic_update(action)
        return plot_summary(record, 0)

    def update_plot(self, plot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(payload) - PLOT_UPDATE_FIELDS)
        if unknown:
            raise ValidationError(
                "园区更新包含不支持的字段",
                details={"unknown_fields": unknown},
            )
        if "revision" not in payload:
            raise ValidationError("更新园区需要 revision", field_name="revision")

        def action(state: dict[str, Any]) -> dict[str, Any]:
            plot = state["plots"].get(plot_id)
            if plot is None:
                raise NotFoundError("园区", plot_id)
            normalized = normalize_plot_payload(
                {
                    "code": payload.get("code", plot["code"]),
                    "name": payload.get("name", plot["name"]),
                    "locality": payload.get("locality", plot["locality"]),
                    "cultivar_focus": payload.get(
                        "cultivar_focus",
                        plot["cultivar_focus"],
                    ),
                    "steward": payload.get("steward", plot["steward"]),
                    "planting_year": payload.get(
                        "planting_year",
                        plot["planting_year"],
                    ),
                    "note": payload.get("note", plot["note"]),
                }
            )
            ensure_unique_plot_code(
                state["plots"],
                normalized["code"],
                excluded_id=plot_id,
            )
            updated = update_plot_record(
                plot,
                payload,
                expected_revision=payload["revision"],
            )
            state["plots"][plot_id] = updated
            tree_count = sum(
                1
                for tree in state["trees"].values()
                if tree["plot_id"] == plot_id
            )
            return plot_summary(updated, tree_count)

        return self.repository.atomic_update(action)

    def confirm_plot(
        self,
        plot_id: str,
        *,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        def action(state: dict[str, Any]) -> dict[str, Any]:
            plot = state["plots"].get(plot_id)
            if plot is None:
                raise NotFoundError("园区", plot_id)
            updated = confirm_plot_record(
                plot,
                state["trees"],
                expected_revision=expected_revision,
            )
            state["plots"][plot_id] = updated
            return plot_summary(
                updated,
                sum(
                    1
                    for tree in state["trees"].values()
                    if tree["plot_id"] == plot_id
                ),
            )

        return self.repository.atomic_update(action)

    def list_trees(
        self,
        *,
        plot_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        state = self.repository.read()
        if plot_id and plot_id not in state["plots"]:
            raise NotFoundError("园区", plot_id)
        trees = []
        for tree in state["trees"].values():
            if plot_id and tree["plot_id"] != plot_id:
                continue
            if status and tree["status"] != status:
                continue
            trees.append(copy_tree(tree))
        trees.sort(key=lambda item: item["code"])
        return {"items": trees, "total": len(trees)}

    def get_tree(self, tree_id: str) -> dict[str, Any]:
        state = self.repository.read()
        tree = state["trees"].get(tree_id)
        if tree is None:
            raise NotFoundError("植株", tree_id)
        return copy_tree(tree)

    def create_tree(self, payload: dict[str, Any]) -> dict[str, Any]:
        def action(state: dict[str, Any]) -> dict[str, Any]:
            plot_id = str(payload.get("plot_id") or "")
            plot = state["plots"].get(plot_id)
            if plot is None:
                raise NotFoundError("园区", plot_id)
            record = create_tree_record(payload, plot, now_iso())
            ensure_unique_tree_code(
                state["trees"],
                plot_id,
                record["code"],
            )
            state["trees"][record["id"]] = record
            return record

        return copy_tree(self.repository.atomic_update(action))

    def retire_tree(
        self,
        tree_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"status", "note", "revision"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "植株结束操作包含不支持的字段",
                details={"unknown_fields": unknown},
            )

        def action(state: dict[str, Any]) -> dict[str, Any]:
            tree = state["trees"].get(tree_id)
            if tree is None:
                raise NotFoundError("植株", tree_id)
            updated = retire_tree_record(
                tree,
                status=str(payload.get("status") or ""),
                note=payload.get("note"),
                expected_revision=payload.get("revision"),
            )
            state["trees"][tree_id] = updated
            return updated

        return copy_tree(self.repository.atomic_update(action))

    def _plot_detail(
        self,
        state: dict[str, Any],
        plot_id: str,
    ) -> dict[str, Any]:
        plot = state["plots"].get(plot_id)
        if plot is None:
            raise NotFoundError("园区", plot_id)
        trees = sorted(
            (
                copy_tree(tree)
                for tree in state["trees"].values()
                if tree["plot_id"] == plot_id
            ),
            key=lambda item: item["code"],
        )
        detail = plot_summary(plot, len(trees))
        detail["trees"] = trees
        return detail


def copy_tree(tree: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": tree["id"],
        "plot_id": tree["plot_id"],
        "code": tree["code"],
        "cultivar": tree["cultivar"],
        "rootstock": tree["rootstock"],
        "planting_year": tree["planting_year"],
        "status": tree["status"],
        "note": tree["note"],
        "revision": tree["revision"],
        "created_at": tree["created_at"],
        "updated_at": tree["updated_at"],
    }
