"""修订冲突、幂等复用与持久化失败的对抗性单元测试。

三类对抗场景中的后两类在此覆盖：

* 对象修订冲突：旧 revision 的写入必须被 409 拦截，且不覆盖较新记录；
* 重复请求不产生额外事实：相同幂等键复用第一次成功结果，同键不同体冲突；
* 落盘失败不替换内存状态：提交阶段（commit）失败时，仓储内存/后续读取
  必须保持提交前状态，而不是返回已经“逻辑写入”的内容。

另含“第一次写入业务成功但后续关系检查失败”的事务对抗：
``Repository.atomic_update`` 在 action 之后执行 ``check_relationships``，
关系不成立时整个事务必须回滚，不能留下半截实体。
"""

from __future__ import annotations

import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.application import CatalogService, ObservationService
from app.errors import ConflictError, DomainError

from _support import (
    DatabaseHarness,
    plot_payload,
    request_context,
    tree_payload,
)


class RevisionConflictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.catalog = CatalogService(self.harness.repository)
        self.observations = ObservationService(self.harness.repository)
        with request_context():
            self.plot = self.catalog.create_plot(plot_payload("OR-5501"))

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_stale_revision_is_rejected_and_record_keeps_newer_state(self) -> None:
        with request_context():
            updated = self.catalog.update_plot(
                self.plot["id"],
                {"name": "较新的名称", "revision": self.plot["revision"]},
            )
        self.assertEqual(updated["revision"], 2)

        # 另一客户端仍持有 revision=1，后写必须失败，不得覆盖 revision=2。
        with request_context():
            with self.assertRaises(ConflictError) as raised:
                self.catalog.update_plot(
                    self.plot["id"],
                    {"name": "过期客户端的名称", "revision": 1},
                )
        self.assertEqual(raised.exception.code, "revision_conflict")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.details["expected"], 1)
        self.assertEqual(raised.exception.details["actual"], 2)

        with request_context():
            detail = self.catalog.get_plot(self.plot["id"])
        self.assertEqual(detail["name"], "较新的名称")
        self.assertEqual(detail["revision"], 2)

    def test_concurrent_confirm_with_same_revision_only_one_wins(self) -> None:
        with request_context():
            self.catalog.create_tree(
                tree_payload(self.plot["id"], "OR-5501-T01", planting_year=2012)
            )

        outcomes: list[dict[str, Any]] = []

        def confirm(_: int) -> dict[str, Any]:
            try:
                with request_context(f"local-admin", f"confirm-race-{_}"):
                    result = self.catalog.confirm_plot(
                        self.plot["id"], expected_revision=1
                    )
                return {"ok": True, "revision": result["revision"]}
            except DomainError as error:
                return {"ok": False, "code": error.code, "status": error.status}

        # 两个请求都基于 revision=1 并发确认；BEGIN IMMEDIATE 串行化事务，
        # 只能有一个成功。负方必须收到稳定的 4xx 业务错误（状态机或修订号
        # 冲突，两条规则都来自规格），绝不能两个都成功或落库成两条事实。
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(confirm, range(2)))

        winners = [item for item in outcomes if item["ok"]]
        losers = [item for item in outcomes if not item["ok"]]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual(len(losers), 1, outcomes)
        self.assertEqual(winners[0]["revision"], 2)
        self.assertIn(
            losers[0]["code"], {"revision_conflict", "plot_already_confirmed"}
        )
        self.assertIn(losers[0]["status"], {409, 412})

        with request_context():
            detail = self.catalog.get_plot(self.plot["id"])
        self.assertEqual(detail["status"], "confirmed")
        self.assertEqual(detail["revision"], 2)


class IdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.catalog = CatalogService(self.harness.repository)

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_repeated_request_with_same_key_adds_no_facts(self) -> None:
        body = plot_payload("OR-5502")
        with request_context("local-admin", "durable-key"):
            first = self.catalog.create_plot(body)
            revision_after_first = self.harness.repository.read()["revision"]
            second = self.catalog.create_plot(body)
            revision_after_second = self.harness.repository.read()["revision"]
            audit = self.harness.repository.list_audit_events(
                resource_id=first["id"]
            )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(revision_after_first, revision_after_second)
        self.assertEqual(len(self.harness.repository.read()["plots"]), 1)
        # 复用响应不得再写审计/outbox：同一资源只有一次 create 事件。
        self.assertEqual(audit["total"], 1)

    def test_same_key_with_different_body_conflicts(self) -> None:
        with request_context(
            "local-admin",
            "reused-key",
            request_hash="fingerprint:OR-5503",
        ):
            self.catalog.create_plot(plot_payload("OR-5503"))
        with request_context(
            "local-admin",
            "reused-key",
            request_hash="fingerprint:OR-5504",
        ):
            with self.assertRaises(ConflictError) as raised:
                self.catalog.create_plot(plot_payload("OR-5504"))
        self.assertEqual(raised.exception.code, "idempotency_key_reused")
        self.assertEqual(raised.exception.status, 409)
        # 失败的复用请求不写入第二个园区。
        state = self.harness.repository.read()
        self.assertEqual(len(state["plots"]), 1)


class RelationshipCheckRollbackTests(unittest.TestCase):
    """对抗场景：业务 action 已“成功”放入实体，但提交前关系检查失败。"""

    def setUp(self) -> None:
        self.harness = DatabaseHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_action_result_violating_relationships_is_rolled_back(self) -> None:
        repository = self.harness.repository

        def insert_orphan_tree(state: dict[str, Any]) -> dict[str, Any]:
            # 直接在工作副本上塞一株引用不存在园区的树。
            state["trees"]["tree_orphan"] = {
                "id": "tree_orphan",
                "schema_version": 1,
                "plot_id": "plot_missing",
                "code": "OR-9999-T01",
                "cultivar": "幽灵梨",
                "rootstock": "杜梨",
                "planting_year": 2020,
                "status": "active",
                "note": "",
                "revision": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            return state["trees"]["tree_orphan"]

        with request_context():
            with self.assertRaises(DomainError) as raised:
                repository.atomic_update(insert_orphan_tree)

        self.assertEqual(raised.exception.code, "state_relationships_invalid")
        self.assertEqual(raised.exception.status, 500)
        # 事务回滚后：实体表、版本表、审计、outbox、状态修订号都不得出现该事实。
        state = repository.read()
        self.assertEqual(state["trees"], {})
        self.assertEqual(state["revision"], 0)
        with repository.database.read_connection() as connection:
            entity_count = connection.execute(
                "SELECT COUNT(*) AS c FROM entities"
            ).fetchone()["c"]
            version_count = connection.execute(
                "SELECT COUNT(*) AS c FROM entity_versions"
            ).fetchone()["c"]
            outbox_count = connection.execute(
                "SELECT COUNT(*) AS c FROM outbox_events"
            ).fetchone()["c"]
        self.assertEqual((entity_count, version_count, outbox_count), (0, 0, 0))


class CommitFailureAtomicityTests(unittest.TestCase):
    """对抗场景：关系检查已通过，但最终 COMMIT 落盘失败。"""

    def setUp(self) -> None:
        self.harness = DatabaseHarness()
        self.catalog = CatalogService(self.harness.repository)

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_failed_commit_does_not_replace_observable_state(self) -> None:
        from contextlib import contextmanager

        database = self.harness.repository.database
        real_connect = database.connect
        state = {"armed": False, "failures": 0}

        @contextmanager
        def failing_transaction(*, immediate: bool = True):
            # 与 Database.transaction 相同的连接生命周期，但在武装期间
            # 让提交点抛出 I/O 错误（模拟磁盘满），随后按生产逻辑回滚。
            connection = real_connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                if state["armed"]:
                    state["armed"] = False
                    state["failures"] += 1
                    raise sqlite3.OperationalError(
                        "disk I/O error (injected for test)"
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

        database.transaction = failing_transaction  # type: ignore[method-assign]

        with request_context():
            self.catalog.create_plot(plot_payload("OR-5510"))

        state["armed"] = True
        try:
            with request_context():
                with self.assertRaises(sqlite3.OperationalError):
                    self.catalog.create_plot(plot_payload("OR-5511"))
        finally:
            del database.transaction

        self.assertEqual(state["failures"], 1)
        # 关键断言：失败之后再次读取，状态必须仍是“一个园区”，
        # 不能出现逻辑已写但落盘失败的 OR-5511。
        state_snapshot = self.harness.repository.read()
        self.assertEqual(len(state_snapshot["plots"]), 1)
        plots = self.catalog.list_plots()
        codes = [item["code"] for item in plots["items"]]
        self.assertEqual(codes, ["OR-5510"])
        self.assertNotIn("OR-5511", codes)


if __name__ == "__main__":
    unittest.main()
