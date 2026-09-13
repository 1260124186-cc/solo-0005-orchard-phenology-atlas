"""季节志用例。"""

from __future__ import annotations

from typing import Any

from ..domain.observation_rules import (
    add_stage_entry,
    complete_observation_record,
    create_observation_record,
    ensure_unique_open_observation,
    observation_summary,
    remove_stage_entry,
    update_observation_note,
)
from ..domain.plot_rules import now_iso
from ..errors import NotFoundError, ValidationError
from ..persistence import Repository


class ObservationService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_observations(
        self,
        *,
        plot_id: str | None = None,
        tree_id: str | None = None,
        season: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        state = self.repository.read()
        items: list[dict[str, Any]] = []
        for observation in state["observations"].values():
            if plot_id and observation["plot_id"] != plot_id:
                continue
            if tree_id and observation["tree_id"] != tree_id:
                continue
            if season and observation["season"] != season:
                continue
            if status and observation["status"] != status:
                continue
            tree = state["trees"].get(observation["tree_id"])
            items.append(observation_summary(observation, tree))
        items.sort(
            key=lambda item: (
                item["season"],
                item["tree_code"],
                item["created_at"],
            ),
            reverse=True,
        )
        return {"items": items, "total": len(items)}

    def get_observation(self, observation_id: str) -> dict[str, Any]:
        state = self.repository.read()
        return self._detail(state, observation_id)

    def start_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        def action(state: dict[str, Any]) -> dict[str, Any]:
            tree_id = str(payload.get("tree_id") or "")
            tree = state["trees"].get(tree_id)
            if tree is None:
                raise NotFoundError("植株", tree_id)
            record = create_observation_record(payload, tree, now_iso())
            ensure_unique_open_observation(
                state["observations"],
                record["tree_id"],
                record["season"],
            )
            state["observations"][record["id"]] = record
            return record

        record = self.repository.atomic_update(action)
        return observation_summary(record, self._tree_snapshot(record["tree_id"]))

    def update_observation(
        self,
        observation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"note", "revision"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "季节志更新包含不支持的字段",
                details={"unknown_fields": unknown},
            )
        if "revision" not in payload:
            raise ValidationError("更新季节志需要 revision", field_name="revision")

        def action(state: dict[str, Any]) -> dict[str, Any]:
            observation = state["observations"].get(observation_id)
            if observation is None:
                raise NotFoundError("季节志", observation_id)
            updated = update_observation_note(
                observation,
                note=str(payload.get("note") or ""),
                expected_revision=payload["revision"],
            )
            state["observations"][observation_id] = updated
            return updated

        updated = self.repository.atomic_update(action)
        return observation_summary(
            updated,
            self._tree_snapshot(updated["tree_id"]),
        )

    def add_stage(
        self,
        observation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "revision" not in payload:
            raise ValidationError("新增阶段需要 revision", field_name="revision")
        revision = payload["revision"]
        entry_payload = {key: value for key, value in payload.items() if key != "revision"}

        def action(state: dict[str, Any]) -> dict[str, Any]:
            observation = state["observations"].get(observation_id)
            if observation is None:
                raise NotFoundError("季节志", observation_id)
            updated = add_stage_entry(
                observation,
                entry_payload,
                expected_revision=revision,
            )
            state["observations"][observation_id] = updated
            return updated

        updated = self.repository.atomic_update(action)
        return observation_summary(
            updated,
            self._tree_snapshot(updated["tree_id"]),
        )

    def remove_stage(
        self,
        observation_id: str,
        stage: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"revision"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "移除阶段包含不支持的字段",
                details={"unknown_fields": unknown},
            )
        if "revision" not in payload:
            raise ValidationError("移除阶段需要 revision", field_name="revision")
        revision = payload["revision"]

        def action(state: dict[str, Any]) -> dict[str, Any]:
            observation = state["observations"].get(observation_id)
            if observation is None:
                raise NotFoundError("季节志", observation_id)
            updated = remove_stage_entry(
                observation,
                stage,
                expected_revision=revision,
            )
            state["observations"][observation_id] = updated
            return updated

        updated = self.repository.atomic_update(action)
        return observation_summary(
            updated,
            self._tree_snapshot(updated["tree_id"]),
        )

    def complete_observation(
        self,
        observation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"revision"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValidationError(
                "完成季节志包含不支持的字段",
                details={"unknown_fields": unknown},
            )
        if "revision" not in payload:
            raise ValidationError("完成季节志需要 revision", field_name="revision")
        revision = payload["revision"]

        def action(state: dict[str, Any]) -> dict[str, Any]:
            observation = state["observations"].get(observation_id)
            if observation is None:
                raise NotFoundError("季节志", observation_id)
            updated = complete_observation_record(
                observation,
                expected_revision=revision,
            )
            state["observations"][observation_id] = updated
            return updated

        updated = self.repository.atomic_update(action)
        return observation_summary(
            updated,
            self._tree_snapshot(updated["tree_id"]),
        )

    def _detail(
        self,
        state: dict[str, Any],
        observation_id: str,
    ) -> dict[str, Any]:
        observation = state["observations"].get(observation_id)
        if observation is None:
            raise NotFoundError("季节志", observation_id)
        return observation_summary(
            observation,
            state["trees"].get(observation["tree_id"]),
        )

    def _tree_snapshot(self, tree_id: str) -> dict[str, Any] | None:
        return self.repository.read()["trees"].get(tree_id)
