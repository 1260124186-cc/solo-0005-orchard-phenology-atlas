"""对比图谱同年与共同阶段约束的业务回归测试。

规则来源：PROJECT_SPEC.md「核心实体 / 对比图谱」与三条工作流之三：

* 两侧季节志必须均为 completed；
* 必须属于同一年份；
* 只使用双方共同阶段，没有共同阶段时拒绝（不补零、不推断）；
* 生成结果不可变，重复生成同一对不产生额外事实。
"""

from __future__ import annotations

import unittest
from typing import Any

from app.application import (
    CatalogService,
    ComparisonService,
    ObservationService,
)
from app.errors import DomainError

from _support import (
    DatabaseHarness,
    observation_payload,
    plot_payload,
    request_context,
    stage_payload,
    tree_payload,
)


def _seed_tree(catalog: CatalogService, plot_code: str, tree_code: str) -> str:
    with request_context():
        plot = catalog.create_plot(
            plot_payload(plot_code, planting_year=2010)
        )
        tree = catalog.create_tree(
            tree_payload(plot["id"], tree_code, planting_year=2012)
        )
    return tree["id"]


def _finish_season(
    observations: ObservationService,
    tree_id: str,
    season: str,
    dates: dict[str, str],
) -> dict[str, Any]:
    with request_context():
        observation = observations.start_observation(
            observation_payload(tree_id, season=season)
        )
        for stage, observed_on in dates.items():
            observation = observations.add_stage(
                observation["id"],
                stage_payload(stage, observed_on, observation["revision"]),
            )
        return observations.complete_observation(
            observation["id"], {"revision": observation["revision"]}
        )


FOUR_REQUIRED_2026 = {
    "bud_burst": "2026-03-14",
    "full_bloom": "2026-04-06",
    "fruit_set": "2026-04-24",
    "harvest": "2026-09-08",
}


class ComparisonRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.catalog = CatalogService(self.harness.repository)
        self.observations = ObservationService(self.harness.repository)
        self.comparisons = ComparisonService(self.harness.repository)
        self.left_tree = _seed_tree(self.catalog, "OR-5401", "OR-5401-T01")
        self.right_tree = _seed_tree(self.catalog, "OR-5402", "OR-5402-T01")

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_rejects_seasons_from_different_years(self) -> None:
        left = _finish_season(
            self.observations,
            self.left_tree,
            "2025",
            {
                "bud_burst": "2025-03-14",
                "full_bloom": "2025-04-06",
                "fruit_set": "2025-04-24",
                "harvest": "2025-09-08",
            },
        )
        right = _finish_season(
            self.observations,
            self.right_tree,
            "2026",
            {
                "bud_burst": "2026-03-14",
                "full_bloom": "2026-04-06",
                "fruit_set": "2026-04-24",
                "harvest": "2026-09-08",
            },
        )
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.comparisons.create_comparison(
                    {
                        "title": "跨年比较",
                        "left_observation_id": left["id"],
                        "right_observation_id": right["id"],
                    }
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.details.get("field"), "season")
        with request_context():
            self.assertEqual(self.comparisons.list_comparisons()["total"], 0)

    def test_rejects_open_observations(self) -> None:
        with request_context():
            left = self.observations.start_observation(
                observation_payload(self.left_tree, season="2026")
            )
            right = self.observations.start_observation(
                observation_payload(self.right_tree, season="2026")
            )
            with self.assertRaises(DomainError) as raised:
                self.comparisons.create_comparison(
                    {
                        "title": "未完成比较",
                        "left_observation_id": left["id"],
                        "right_observation_id": right["id"],
                    }
                )
        self.assertEqual(raised.exception.code, "season_not_completed")
        self.assertEqual(raised.exception.status, 412)

    def test_rejects_pair_without_common_stage(self) -> None:
        # 任意能完成的季节志都含四个必需阶段，因此“无共同阶段”无法通过正常
        # 用例构造；这里直接在领域层用两条同年、已完成但条目不相交的记录验证
        # 规则（规格：缺少共同阶段时拒绝，不补零、不推断）。
        from app.domain.comparison_rules import create_comparison_record
        from app.domain.plot_rules import now_iso

        disjoint_left = {
            "id": "season_left",
            "tree_id": self.left_tree,
            "season": "2026",
            "status": "completed",
            "entries": [
                {"stage": "bud_burst", "observed_on": "2026-03-14"},
                {"stage": "full_bloom", "observed_on": "2026-04-06"},
            ],
        }
        disjoint_right = {
            "id": "season_right",
            "tree_id": self.right_tree,
            "season": "2026",
            "status": "completed",
            "entries": [
                {"stage": "first_bloom", "observed_on": "2026-03-30"},
                {"stage": "leaf_fall", "observed_on": "2026-11-18"},
            ],
        }
        with self.assertRaises(DomainError) as raised:
            create_comparison_record(
                {
                    "title": "无共同阶段",
                    "left_observation_id": "season_left",
                    "right_observation_id": "season_right",
                },
                disjoint_left,
                disjoint_right,
                None,
                None,
                now_iso(),
            )
        self.assertEqual(raised.exception.code, "no_common_stage")
        self.assertEqual(raised.exception.status, 412)

    def test_offsets_use_only_common_stages_and_are_right_minus_left(self) -> None:
        left = _finish_season(
            self.observations,
            self.left_tree,
            "2026",
            {
                "bud_burst": "2026-03-10",
                "full_bloom": "2026-04-01",
                "fruit_set": "2026-04-18",
                "harvest": "2026-09-02",
            },
        )
        right = _finish_season(
            self.observations,
            self.right_tree,
            "2026",
            {
                "bud_burst": "2026-03-15",
                "full_bloom": "2026-04-05",
                "fruit_set": "2026-04-22",
                "harvest": "2026-09-07",
                # 右侧多一个落叶期，左侧没有：比较结果不得包含它。
                "leaf_fall": "2026-11-20",
            },
        )
        with request_context():
            comparison = self.comparisons.create_comparison(
                {
                    "title": "2026 秋白梨与蜜香梨对齐",
                    "left_observation_id": left["id"],
                    "right_observation_id": right["id"],
                }
            )
        stages = [row["stage"] for row in comparison["stage_offsets"]]
        self.assertEqual(stages, ["bud_burst", "full_bloom", "fruit_set", "harvest"])
        self.assertNotIn("leaf_fall", stages)
        offsets = {row["stage"]: row["offset_days"] for row in comparison["stage_offsets"]}
        self.assertEqual(offsets["bud_burst"], 5)
        self.assertEqual(offsets["harvest"], 5)
        self.assertEqual(comparison["season"], "2026")
        self.assertEqual(comparison["summary"]["common_stage_count"], 4)

    def test_recreating_same_pair_returns_existing_record(self) -> None:
        left = _finish_season(
            self.observations,
            self.left_tree,
            "2026",
            {
                "bud_burst": "2026-03-10",
                "full_bloom": "2026-04-01",
                "fruit_set": "2026-04-18",
                "harvest": "2026-09-02",
            },
        )
        right = _finish_season(
            self.observations,
            self.right_tree,
            "2026",
            {
                "bud_burst": "2026-03-15",
                "full_bloom": "2026-04-05",
                "fruit_set": "2026-04-22",
                "harvest": "2026-09-07",
            },
        )
        payload = {
            "title": "重复对齐",
            "left_observation_id": left["id"],
            "right_observation_id": right["id"],
        }
        with request_context():
            first = self.comparisons.create_comparison(payload)
            state_revision_after_first = self.harness.repository.read()["revision"]
            second = self.comparisons.create_comparison({**payload, "title": "另一个标题"})
            state_revision_after_second = self.harness.repository.read()["revision"]
        # 同一对季节志重复生成不产生第二条事实。
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["title"], "重复对齐")
        self.assertEqual(state_revision_after_first, state_revision_after_second)
        with request_context():
            self.assertEqual(self.comparisons.list_comparisons()["total"], 1)

    def test_same_observation_on_both_sides_is_rejected(self) -> None:
        only = _finish_season(
            self.observations,
            self.left_tree,
            "2026",
            {
                "bud_burst": "2026-03-14",
                "full_bloom": "2026-04-06",
                "fruit_set": "2026-04-24",
                "harvest": "2026-09-08",
            },
        )
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.comparisons.create_comparison(
                    {
                        "title": "自比较",
                        "left_observation_id": only["id"],
                        "right_observation_id": only["id"],
                    }
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.details.get("field"), "right_observation_id")


if __name__ == "__main__":
    unittest.main()
