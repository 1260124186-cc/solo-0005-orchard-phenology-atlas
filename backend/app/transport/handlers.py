"""API 处理器与输入输出映射。"""

from __future__ import annotations

from typing import Any

from ..application import (
    BriefService,
    CatalogService,
    ComparisonService,
    ObservationService,
)
from ..domain.stages import STAGES
from ..errors import ValidationError
from .router import Router


class ApiHandlers:
    def __init__(
        self,
        catalog: CatalogService,
        observations: ObservationService,
        comparisons: ComparisonService,
        briefs: BriefService,
    ) -> None:
        self.catalog = catalog
        self.observations = observations
        self.comparisons = comparisons
        self.briefs = briefs

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "orchard-phenology-atlas",
            "schema_version": 1,
        }

    def stage_catalog(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "key": stage.key,
                    "label": stage.label,
                    "rank": stage.rank,
                    "required_for_completion": stage.required_for_completion,
                }
                for stage in STAGES
            ]
        }

    def list_plots(
        self,
        *,
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        return self.catalog.list_plots(
            status=_optional_query(query, "status"),
            query=_optional_query(query, "q"),
        )

    def create_plot(self, *, body: dict[str, Any]) -> dict[str, Any]:
        return self.catalog.create_plot(body)

    def get_plot(self, *, params: dict[str, str]) -> dict[str, Any]:
        return self.catalog.get_plot(params["plot_id"])

    def update_plot(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.catalog.update_plot(params["plot_id"], body)

    def confirm_plot(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"revision"}
        _reject_unknown(body, allowed, "确认园区")
        return self.catalog.confirm_plot(
            params["plot_id"],
            expected_revision=_optional_revision(body),
        )

    def list_trees(
        self,
        *,
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        return self.catalog.list_trees(
            plot_id=_optional_query(query, "plot_id"),
            status=_optional_query(query, "status"),
        )

    def create_tree(self, *, body: dict[str, Any]) -> dict[str, Any]:
        return self.catalog.create_tree(body)

    def get_tree(self, *, params: dict[str, str]) -> dict[str, Any]:
        return self.catalog.get_tree(params["tree_id"])

    def retire_tree(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.catalog.retire_tree(params["tree_id"], body)

    def list_observations(
        self,
        *,
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        return self.observations.list_observations(
            plot_id=_optional_query(query, "plot_id"),
            tree_id=_optional_query(query, "tree_id"),
            season=_optional_query(query, "season"),
            status=_optional_query(query, "status"),
        )

    def create_observation(self, *, body: dict[str, Any]) -> dict[str, Any]:
        return self.observations.start_observation(body)

    def get_observation(self, *, params: dict[str, str]) -> dict[str, Any]:
        return self.observations.get_observation(params["observation_id"])

    def update_observation(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.observations.update_observation(
            params["observation_id"],
            body,
        )

    def add_observation_stage(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.observations.add_stage(params["observation_id"], body)

    def remove_observation_stage(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.observations.remove_stage(
            params["observation_id"],
            params["stage"],
            body,
        )

    def complete_observation(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.observations.complete_observation(
            params["observation_id"],
            body,
        )

    def list_comparisons(self) -> dict[str, Any]:
        return self.comparisons.list_comparisons()

    def create_comparison(self, *, body: dict[str, Any]) -> dict[str, Any]:
        return self.comparisons.create_comparison(body)

    def get_comparison(self, *, params: dict[str, str]) -> dict[str, Any]:
        return self.comparisons.get_comparison(params["comparison_id"])

    def list_briefs(
        self,
        *,
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        return self.briefs.list_briefs(plot_id=_optional_query(query, "plot_id"))

    def create_brief(
        self,
        *,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.briefs.create_brief(params["plot_id"], body)

    def get_brief(self, *, params: dict[str, str]) -> dict[str, Any]:
        return self.briefs.get_brief(params["brief_id"])


def build_router(handlers: ApiHandlers) -> Router:
    router = Router()
    router.add("GET", "/api/health", handlers.health)
    router.add("GET", "/api/stages", handlers.stage_catalog)

    router.add("GET", "/api/plots", handlers.list_plots)
    router.add("PUT", "/api/plots", handlers.create_plot)
    router.add("GET", "/api/plots/{plot_id}", handlers.get_plot)
    router.add("PATCH", "/api/plots/{plot_id}", handlers.update_plot)
    router.add("PUT", "/api/plots/{plot_id}/confirm", handlers.confirm_plot)
    router.add("PUT", "/api/plots/{plot_id}/briefs", handlers.create_brief)

    router.add("GET", "/api/trees", handlers.list_trees)
    router.add("PUT", "/api/trees", handlers.create_tree)
    router.add("GET", "/api/trees/{tree_id}", handlers.get_tree)
    router.add("PUT", "/api/trees/{tree_id}/close", handlers.retire_tree)

    router.add("GET", "/api/observations", handlers.list_observations)
    router.add("PUT", "/api/observations", handlers.create_observation)
    router.add("GET", "/api/observations/{observation_id}", handlers.get_observation)
    router.add(
        "PATCH",
        "/api/observations/{observation_id}",
        handlers.update_observation,
    )
    router.add(
        "PUT",
        "/api/observations/{observation_id}/stages",
        handlers.add_observation_stage,
    )
    router.add(
        "DELETE",
        "/api/observations/{observation_id}/stages/{stage}",
        handlers.remove_observation_stage,
    )
    router.add(
        "PUT",
        "/api/observations/{observation_id}/complete",
        handlers.complete_observation,
    )

    router.add("GET", "/api/comparisons", handlers.list_comparisons)
    router.add("PUT", "/api/comparisons", handlers.create_comparison)
    router.add(
        "GET",
        "/api/comparisons/{comparison_id}",
        handlers.get_comparison,
    )

    router.add("GET", "/api/briefs", handlers.list_briefs)
    router.add("GET", "/api/briefs/{brief_id}", handlers.get_brief)
    return router


def _optional_query(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[-1].strip()
    return value or None


def _optional_revision(body: dict[str, Any]) -> int | None:
    if "revision" not in body:
        return None
    value = body["revision"]
    if isinstance(value, bool):
        raise ValidationError("修订号必须是整数", field_name="revision")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("修订号必须是整数", field_name="revision") from exc
    if revision < 1:
        raise ValidationError("修订号必须大于零", field_name="revision")
    return revision


def _reject_unknown(
    body: dict[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ValidationError(
            f"{label}包含不支持的字段",
            details={"unknown_fields": unknown},
        )
