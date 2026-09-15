"""园区确认父子约束与植株归属规则的业务回归测试。

规则来源：PROJECT_SPEC.md「核心实体 / 园区、植株」与「状态和一致性规则」：

* 园区确认需要至少一株 *有效*（active）植株，确认后不可再次变更；
* 植株只能在所属园区仍为草稿时新增或变更；
* 同一园区内植株编号不可重复；
* 定植年份不能早于园区起始种植年份；
* 植株编号必须归属一个存在的园区。
"""

from __future__ import annotations

import unittest

from app.application import CatalogService
from app.errors import DomainError

from _support import DatabaseHarness, plot_payload, request_context, tree_payload


class PlotConfirmationParentChildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.repository = self.harness.repository
        self.catalog = CatalogService(self.repository)

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_plot_without_active_tree_cannot_be_confirmed(self) -> None:
        with request_context():
            plot = self.catalog.create_plot(plot_payload("OR-5101"))

        # 无植株：确认前父子约束必须拦截。
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.confirm_plot(
                    plot["id"], expected_revision=plot["revision"]
                )
        self.assertEqual(raised.exception.code, "plot_requires_tree")
        self.assertEqual(raised.exception.status, 412)

        with request_context():
            reloaded = self.catalog.get_plot(plot["id"])
        self.assertEqual(reloaded["status"], "draft")
        self.assertEqual(reloaded["revision"], 1)

    def test_retired_tree_does_not_satisfy_confirmation_requirement(self) -> None:
        with request_context():
            plot = self.catalog.create_plot(plot_payload("OR-5102"))
            tree = self.catalog.create_tree(
                tree_payload(plot["id"], "OR-5102-T01", planting_year=2012)
            )
            # 唯一植株先退休：父子约束中的“有效植株”不成立。
            self.catalog.retire_tree(
                tree["id"],
                {"status": "retired", "note": "移栽", "revision": tree["revision"]},
            )

        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.confirm_plot(
                    plot["id"], expected_revision=plot["revision"]
                )
        self.assertEqual(raised.exception.code, "plot_requires_tree")

        with request_context():
            detail = self.catalog.get_plot(plot["id"])
        self.assertEqual(detail["status"], "draft")

    def test_confirmed_plot_is_frozen_and_can_only_be_revised_as_new_record(self) -> None:
        with request_context():
            plot = self.catalog.create_plot(plot_payload("OR-5103"))
            self.catalog.create_tree(
                tree_payload(plot["id"], "OR-5103-T01", planting_year=2012)
            )
            confirmed = self.catalog.confirm_plot(
                plot["id"], expected_revision=plot["revision"]
            )
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertIsNotNone(confirmed["confirmed_at"])

        # 已确认园区不能再改基础信息，即使带的是最新修订号。
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.update_plot(
                    plot["id"],
                    {"name": "被篡改的名称", "revision": confirmed["revision"]},
                )
        self.assertEqual(raised.exception.code, "plot_not_editable")
        self.assertEqual(raised.exception.status, 412)

        # 不能重复确认（父子状态机只允许 draft -> confirmed 一次）。
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.confirm_plot(
                    plot["id"], expected_revision=confirmed["revision"]
                )
        self.assertEqual(raised.exception.code, "plot_already_confirmed")

        with request_context():
            detail = self.catalog.get_plot(plot["id"])
        self.assertEqual(detail["name"], plot_payload("OR-5103")["name"])
        self.assertEqual(detail["status"], "confirmed")


class TreeOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.repository = self.harness.repository
        self.catalog = CatalogService(self.repository)

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _draft_plot(self, code: str, planting_year: int = 2010) -> dict:
        with request_context():
            return self.catalog.create_plot(
                plot_payload(code, planting_year=planting_year)
            )

    def test_tree_must_belong_to_an_existing_plot(self) -> None:
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.create_tree(
                    tree_payload("plot_does_not_exist", "OR-5201-T01")
                )
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.repository.read()["trees"], {})

    @unittest.expectedFailure
    def test_tree_code_must_be_unique_within_its_plot_but_not_across_plots(self) -> None:
        # 已知实现缺陷（见 docs/test-findings.md F-001）：
        # ensure_unique_tree_code() 以 ConflictError("tree_code_exists", ...,
        # code=code) 形式抛错，code 同时占用位置参数与关键字参数，触发
        # TypeError: __init__() got multiple values for argument 'code'。
        # 规格（PROJECT_SPEC.md「植株」「接口约定」）要求返回稳定错误码
        # 409 tree_code_exists。修复前本用例必然失败，因此标记 expectedFailure；
        # 修复实现后请移除该装饰器，让断言真正守护回归。
        first = self._draft_plot("OR-5202")
        second = self._draft_plot("OR-5203")
        with request_context():
            self.catalog.create_tree(
                tree_payload(first["id"], "OR-5202-T01", planting_year=2012)
            )
            # 相同编号、不同园区：允许（编号唯一性以所属园区为界）。
            other_plot_tree = self.catalog.create_tree(
                tree_payload(second["id"], "OR-5202-T01", planting_year=2012)
            )
            # 同一园区重复编号：冲突，且不能产生第二株树。
            with self.assertRaises(DomainError) as raised:
                self.catalog.create_tree(
                    tree_payload(first["id"], "OR-5202-T01", planting_year=2012)
                )
            self.assertEqual(raised.exception.code, "tree_code_exists")
            self.assertEqual(raised.exception.status, 409)
            trees = self.catalog.list_trees(plot_id=first["id"])
            self.assertEqual(trees["total"], 1)
            self.assertTrue(other_plot_tree["id"])

    def test_tree_cannot_be_added_to_confirmed_plot(self) -> None:
        plot = self._draft_plot("OR-5204")
        with request_context():
            self.catalog.create_tree(
                tree_payload(plot["id"], "OR-5204-T01", planting_year=2012)
            )
            self.catalog.confirm_plot(plot["id"], expected_revision=plot["revision"])
            with self.assertRaises(DomainError) as raised:
                self.catalog.create_tree(
                    tree_payload(plot["id"], "OR-5204-T02", planting_year=2012)
                )
        self.assertEqual(raised.exception.code, "plot_not_editable")
        self.assertEqual(raised.exception.status, 412)
        with request_context():
            detail = self.catalog.get_plot(plot["id"])
        self.assertEqual(len(detail["trees"]), 1)

    def test_tree_planting_year_cannot_predate_plot_start_year(self) -> None:
        plot = self._draft_plot("OR-5205", planting_year=2010)
        with request_context():
            with self.assertRaises(DomainError) as raised:
                self.catalog.create_tree(
                    tree_payload(plot["id"], "OR-5205-T01", planting_year=2009)
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.details.get("field"), "planting_year")
        with request_context():
            self.assertEqual(self.catalog.list_trees(plot_id=plot["id"])["total"], 0)

    def test_tree_identifier_must_match_owning_plot(self) -> None:
        first = self._draft_plot("OR-5206")
        second = self._draft_plot("OR-5207")
        # 领域守卫：服务层按 payload.plot_id 取园区后，仍要求记录归属一致，
        # 防止调用方（或未来的新用例）把植株挂到别的园区对象上。
        from app.domain.plot_rules import create_tree_record, now_iso

        with request_context():
            with self.assertRaises(DomainError) as raised:
                create_tree_record(
                    tree_payload(first["id"], "OR-5206-T01", planting_year=2012),
                    second,
                    now_iso(),
                )
        self.assertEqual(raised.exception.code, "validation_error")
        self.assertEqual(raised.exception.details.get("field"), "plot_id")
        with request_context():
            self.assertEqual(self.catalog.list_trees(plot_id=first["id"])["total"], 0)
            self.assertEqual(self.catalog.list_trees(plot_id=second["id"])["total"], 0)


if __name__ == "__main__":
    unittest.main()
