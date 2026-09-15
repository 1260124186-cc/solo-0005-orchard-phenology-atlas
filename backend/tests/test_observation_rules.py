"""季节志与物候条目的业务回归测试。

规则来源：PROJECT_SPEC.md「核心实体 / 季节志、物候条目」与「状态和一致性规则」：

* 同一季节志内一个阶段只能出现一次；
* 阶段日期必须随九个物候阶段的既定顺序单调不倒退，并落在观察窗口内；
* 完成至少需要 bud_burst / full_bloom / fruit_set / harvest；
* 季节志完成后不可增删条目或修改；
* 同一植株同一年份只能有一份季节志。
"""

from __future__ import annotations

import unittest
from typing import Any

from app.application import CatalogService, ObservationService
from app.errors import DomainError

from _support import (
    DatabaseHarness,
    observation_payload,
    plot_payload,
    request_context,
    stage_payload,
    tree_payload,
)


class ObservationRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.catalog = CatalogService(self.harness.repository)
        self.observations = ObservationService(self.harness.repository)
        with request_context():
            plot = self.catalog.create_plot(plot_payload("OR-5301"))
            self.tree = self.catalog.create_tree(
                tree_payload(plot["id"], "OR-5301-T01", planting_year=2012)
            )
        self.tree_id = self.tree["id"]

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _start(self, season: str = "2026") -> dict[str, Any]:
        with request_context():
            return self.observations.start_observation(
                observation_payload(self.tree_id, season=season)
            )

    def test_stage_dates_must_follow_established_phenology_order(self) -> None:
        observation = self._start()
        # 先按顺序登记盛花期，再试图登记日期更晚但阶段更早的萌芽期：
        # 阶段 rank 回退本身非法；另测日期倒退。
        with request_context():
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("bud_burst", "2026-03-14", observation["revision"]),
            )
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("full_bloom", "2026-04-06", observation["revision"]),
            )
            # 初花期(rank 30)插在萌芽(20)与盛花(40)之间，日期却早于萌芽期：
            # 日期单调性必须拦截。
            with self.assertRaises(DomainError) as raised:
                self.observations.add_stage(
                    observation["id"],
                    stage_payload("first_bloom", "2026-03-01", observation["revision"]),
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.status, 422)

        with request_context():
            detail = self.observations.get_observation(observation["id"])
        self.assertEqual([entry["stage"] for entry in detail["entries"]],
                         ["bud_burst", "full_bloom"])

    def test_completion_requires_all_four_required_stages(self) -> None:
        observation = self._start()
        with request_context():
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("bud_burst", "2026-03-14", observation["revision"]),
            )
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("full_bloom", "2026-04-06", observation["revision"]),
            )
            # 缺 fruit_set 与 harvest：完成必须被拒绝，且错误详情列出缺失阶段。
            with self.assertRaises(DomainError) as raised:
                self.observations.complete_observation(
                    observation["id"], {"revision": observation["revision"]}
                )
        self.assertEqual(raised.exception.code, "required_stages_missing")
        self.assertEqual(raised.exception.status, 412)
        self.assertEqual(
            set(raised.exception.details["missing"]), {"fruit_set", "harvest"}
        )

        with request_context():
            detail = self.observations.get_observation(observation["id"])
        self.assertEqual(detail["status"], "open")

    def test_optional_stages_alone_do_not_unlock_completion(self) -> None:
        # 只有可选阶段（芽膨大、落叶）即使日期合法也不能完成季节志。
        observation = self._start()
        with request_context():
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("bud_swell", "2026-03-01", observation["revision"]),
            )
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("leaf_fall", "2026-11-20", observation["revision"]),
            )
            with self.assertRaises(DomainError) as raised:
                self.observations.complete_observation(
                    observation["id"], {"revision": observation["revision"]}
                )
        self.assertEqual(raised.exception.code, "required_stages_missing")
        self.assertEqual(
            set(raised.exception.details["missing"]),
            {"bud_burst", "full_bloom", "fruit_set", "harvest"},
        )

    def test_duplicate_stage_in_one_season_is_rejected(self) -> None:
        observation = self._start()
        with request_context():
            observation = self.observations.add_stage(
                observation["id"],
                stage_payload("bud_burst", "2026-03-14", observation["revision"]),
            )
            with self.assertRaises(DomainError) as raised:
                self.observations.add_stage(
                    observation["id"],
                    stage_payload("bud_burst", "2026-03-15", observation["revision"]),
                )
        self.assertEqual(raised.exception.code, "stage_exists")
        self.assertEqual(raised.exception.status, 409)
        with request_context():
            detail = self.observations.get_observation(observation["id"])
        self.assertEqual(len(detail["entries"]), 1)
        self.assertEqual(detail["entries"][0]["observed_on"], "2026-03-14")

    def test_date_outside_season_window_is_rejected(self) -> None:
        observation = self._start(season="2026")
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.observations.add_stage(
                    observation["id"],
                    stage_payload("bud_burst", "2025-06-01", observation["revision"]),
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.details.get("field"), "observed_on")

    def test_completed_observation_is_immutable(self) -> None:
        observation = self._start()
        dates = [
            ("bud_burst", "2026-03-14"),
            ("full_bloom", "2026-04-06"),
            ("fruit_set", "2026-04-24"),
            ("harvest", "2026-09-08"),
        ]
        with request_context():
            for stage, observed_on in dates:
                observation = self.observations.add_stage(
                    observation["id"],
                    stage_payload(stage, observed_on, observation["revision"]),
                )
            completed = self.observations.complete_observation(
                observation["id"], {"revision": observation["revision"]}
            )
        self.assertEqual(completed["status"], "completed")

        # 完成后再补录：禁止。
        with request_context():
            with self.assertRaises(DomainError) as add_raised:
                self.observations.add_stage(
                    completed["id"],
                    stage_payload("leaf_fall", "2026-11-20", completed["revision"]),
                )
            # 删除：禁止。
            with self.assertRaises(DomainError) as remove_raised:
                self.observations.remove_stage(
                    completed["id"],
                    "harvest",
                    {"revision": completed["revision"]},
                )
            # 修改说明：禁止。
            with self.assertRaises(DomainError) as patch_raised:
                self.observations.update_observation(
                    completed["id"],
                    {"note": "完成后追加", "revision": completed["revision"]},
                )
        self.assertEqual(add_raised.exception.code, "season_not_editable")
        self.assertEqual(remove_raised.exception.code, "season_not_editable")
        self.assertEqual(patch_raised.exception.code, "season_not_editable")
        for error in (add_raised.exception, remove_raised.exception, patch_raised.exception):
            self.assertEqual(error.status, 412)

        with request_context():
            detail = self.observations.get_observation(completed["id"])
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(len(detail["entries"]), 4)
        self.assertEqual(detail["note"], "")

    def test_only_one_observation_per_tree_and_season(self) -> None:
        with request_context():
            first = self.observations.start_observation(
                observation_payload(self.tree_id, season="2026")
            )
            with self.assertRaises(DomainError) as raised:
                self.observations.start_observation(
                    observation_payload(self.tree_id, season="2026", observer="另一人")
                )
        self.assertEqual(raised.exception.code, "season_exists")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.details["existing_id"], first["id"])
        with request_context():
            listing = self.observations.list_observations(tree_id=self.tree_id)
        self.assertEqual(listing["total"], 1)

    def test_cannot_open_observation_for_retired_tree(self) -> None:
        with request_context():
            retired = self.catalog.retire_tree(
                self.tree_id,
                {"status": "lost", "note": "枯死", "revision": self.tree["revision"]},
            )
            with self.assertRaises(DomainError) as raised:
                self.observations.start_observation(
                    observation_payload(self.tree_id, season="2026")
                )
        self.assertEqual(raised.exception.code, "tree_not_active")
        self.assertEqual(raised.exception.status, 412)
        self.assertEqual(retired["status"], "lost")


if __name__ == "__main__":
    unittest.main()
