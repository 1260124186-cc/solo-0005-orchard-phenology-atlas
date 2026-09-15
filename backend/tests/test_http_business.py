"""真实 HTTP 层的业务回归测试。

使用与生产相同的入口（``create_server`` + 标准库 ThreadingHTTPServer），
数据落在每个用例独立的临时目录中，通过真实 socket 发 JSON 请求，断言：

* PROJECT_SPEC.md「接口约定」规定的状态码与稳定错误码；
* 成功写入真实落盘（重启进程/仓储后仍可读取）；
* 幂等键在真实 HTTP 指纹下的复用与冲突；
* 同一操作的并发 HTTP 请求不产生额外事实；
* 第一阶段业务成功但后续关系检查失败时整笔回滚（通过重复建树触发）。
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.config import RuntimeConfig
from app.persistence import Database, Repository
from app.transport.server import create_server

from _support import (
    REQUIRED_STAGE_DATES_2026,
    http_request,
    observation_payload,
    plot_payload,
    stage_payload,
    tree_payload,
)


class HttpBusinessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.repository = Repository(Database(self.data_dir / "atlas.sqlite3"))
        self.repository.open()
        self.server = create_server(
            RuntimeConfig(
                host="127.0.0.1",
                port=0,
                data_dir=self.data_dir,
                request_limit=1_048_576,
                max_workers=16,
            ),
            self.repository,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.repository.close()
        self.temporary.cleanup()

    # --- helpers -------------------------------------------------------

    def api(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        actor: str = "local-admin",
    ) -> tuple[int, dict[str, Any]]:
        return http_request(
            self.base, method, path, body, actor=actor, idempotency_key=key
        )

    def create_draft_plot_with_tree(
        self,
        code: str = "OR-5601",
        *,
        confirm: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _, plot = self.api("PUT", "/plots", plot_payload(code))
        _, tree = self.api(
            "PUT",
            "/trees",
            tree_payload(plot["id"], f"{code}-T01"),
        )
        if confirm:
            status, confirmed = self.api(
                "PUT",
                f"/plots/{plot['id']}/confirm",
                {"revision": plot["revision"]},
            )
            self.assertEqual(status, 200, confirmed)
            plot = confirmed
        return plot, tree

    def complete_observation_over_http(
        self,
        tree: dict[str, Any],
        season: str = "2026",
        dates: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        dates = dates or REQUIRED_STAGE_DATES_2026
        _, observation = self.api(
            "PUT",
            "/observations",
            observation_payload(tree["id"], season=season),
        )
        for stage, observed_on in dates.items():
            status, payload = self.api(
                "PUT",
                f"/observations/{observation['id']}/stages",
                stage_payload(stage, observed_on, observation["revision"]),
            )
            self.assertEqual(status, 200, payload)
            observation = payload
        status, completed = self.api(
            "PUT",
            f"/observations/{observation['id']}/complete",
            {"revision": observation["revision"]},
        )
        self.assertEqual(status, 200, completed)
        return completed

    # --- 园区确认父子约束 ----------------------------------------------

    def test_confirm_empty_plot_returns_412_and_persists_nothing(self) -> None:
        _, plot = self.api("PUT", "/plots", plot_payload("OR-5610"))
        status, payload = self.api(
            "PUT", f"/plots/{plot['id']}/confirm", {"revision": plot["revision"]}
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "plot_requires_tree")

        status, reloaded = self.api("GET", f"/plots/{plot['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["status"], "draft")

    def test_confirm_plot_with_tree_persists_across_repository_restart(self) -> None:
        plot, _ = self.create_draft_plot_with_tree("OR-5611", confirm=True)
        self.assertEqual(plot["status"], "confirmed")

        # 用同一数据文件新建仓储（模拟服务重启），结果必须仍在磁盘上。
        restarted = Repository(Database(self.data_dir / "atlas.sqlite3"))
        restarted.open()
        try:
            state = restarted.read()
            persisted = next(iter(state["plots"].values()))
            self.assertEqual(persisted["status"], "confirmed")
            self.assertEqual(len(state["trees"]), 1)
        finally:
            restarted.close()

    def test_mutation_on_confirmed_plot_returns_412(self) -> None:
        plot, _ = self.create_draft_plot_with_tree("OR-5612", confirm=True)
        status, payload = self.api(
            "PATCH",
            f"/plots/{plot['id']}",
            {"name": "越权改名", "revision": plot["revision"]},
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "plot_not_editable")

        status, payload = self.api(
            "PUT",
            f"/plots/{plot['id']}/confirm",
            {"revision": plot["revision"]},
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "plot_already_confirmed")

    # --- 植株编号归属 ---------------------------------------------------

    def test_tree_for_unknown_plot_returns_404_and_no_partial_write(self) -> None:
        status, payload = self.api(
            "PUT",
            "/trees",
            tree_payload("plot_missing_id", "OR-5613-T01"),
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        status, listing = self.api("GET", "/trees")
        self.assertEqual(status, 200)
        self.assertEqual(listing["total"], 0)

    @unittest.expectedFailure
    def test_duplicate_tree_code_returns_409_not_500(self) -> None:
        # 已知实现缺陷 F-001（docs/test-findings.md）：重复植株编号在领域层
        # 抛 TypeError，HTTP 最终返回 500 internal_error；规格要求稳定错误码
        # 409 tree_code_exists。修复后请移除 expectedFailure。
        plot, _ = self.create_draft_plot_with_tree("OR-5614")
        status, first = self.api(
            "PUT", "/trees", tree_payload(plot["id"], "OR-5614-T02")
        )
        self.assertEqual(status, 200, first)
        status, payload = self.api(
            "PUT", "/trees", tree_payload(plot["id"], "OR-5614-T02")
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "tree_code_exists")

    # --- 阶段顺序 / 必需阶段 / 完成后不可编辑 ---------------------------

    def test_stage_regression_is_rejected_over_http(self) -> None:
        _, tree = self.create_draft_plot_with_tree("OR-5615")
        _, observation = self.api(
            "PUT", "/observations", observation_payload(tree["id"])
        )
        _, observation = self.api(
            "PUT",
            f"/observations/{observation['id']}/stages",
            stage_payload("full_bloom", "2026-04-06", observation["revision"]),
        )
        # 萌芽期 rank 更早，试图排在盛花期之后：顺序非法。
        status, payload = self.api(
            "PUT",
            f"/observations/{observation['id']}/stages",
            stage_payload("bud_burst", "2026-04-07", observation["revision"]),
        )
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_error")

    def test_completion_without_required_stages_returns_412(self) -> None:
        _, tree = self.create_draft_plot_with_tree("OR-5616")
        _, observation = self.api(
            "PUT", "/observations", observation_payload(tree["id"])
        )
        _, observation = self.api(
            "PUT",
            f"/observations/{observation['id']}/stages",
            stage_payload("bud_burst", "2026-03-14", observation["revision"]),
        )
        status, payload = self.api(
            "PUT",
            f"/observations/{observation['id']}/complete",
            {"revision": observation["revision"]},
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "required_stages_missing")
        self.assertEqual(
            set(payload["error"]["details"]["missing"]),
            {"full_bloom", "fruit_set", "harvest"},
        )

    def test_completed_observation_rejects_further_writes(self) -> None:
        _, tree = self.create_draft_plot_with_tree("OR-5617")
        completed = self.complete_observation_over_http(tree)
        status, payload = self.api(
            "PUT",
            f"/observations/{completed['id']}/stages",
            stage_payload("leaf_fall", "2026-11-20", completed["revision"]),
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "season_not_editable")
        status, payload = self.api(
            "DELETE",
            f"/observations/{completed['id']}/stages/harvest",
            {"revision": completed["revision"]},
        )
        self.assertEqual(status, 412)
        self.assertEqual(payload["error"]["code"], "season_not_editable")

    # --- 同年比较 -------------------------------------------------------

    def test_comparison_different_years_returns_422(self) -> None:
        plot_a, tree_a = self.create_draft_plot_with_tree("OR-5620", confirm=True)
        plot_b, tree_b = self.create_draft_plot_with_tree("OR-5621", confirm=True)
        left_2025 = {
            "bud_burst": "2025-03-14",
            "full_bloom": "2025-04-06",
            "fruit_set": "2025-04-24",
            "harvest": "2025-09-08",
        }
        left = self.complete_observation_over_http(tree_a, "2025", left_2025)
        right = self.complete_observation_over_http(tree_b, "2026")
        status, payload = self.api(
            "PUT",
            "/comparisons",
            {
                "title": "跨年",
                "left_observation_id": left["id"],
                "right_observation_id": right["id"],
            },
        )
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertEqual(payload["error"]["details"]["field"], "season")

    def test_successful_comparison_persists_offsets(self) -> None:
        _, tree_a = self.create_draft_plot_with_tree("OR-5622", confirm=True)
        _, tree_b = self.create_draft_plot_with_tree("OR-5623", confirm=True)
        left = self.complete_observation_over_http(
            tree_a,
            dates={
                "bud_burst": "2026-03-10",
                "full_bloom": "2026-04-01",
                "fruit_set": "2026-04-18",
                "harvest": "2026-09-02",
            },
        )
        right = self.complete_observation_over_http(
            tree_b,
            dates={
                "bud_burst": "2026-03-15",
                "full_bloom": "2026-04-05",
                "fruit_set": "2026-04-22",
                "harvest": "2026-09-07",
            },
        )
        status, comparison = self.api(
            "PUT",
            "/comparisons",
            {
                "title": "2026 对齐",
                "left_observation_id": left["id"],
                "right_observation_id": right["id"],
            },
        )
        self.assertEqual(status, 200, comparison)
        self.assertEqual(
            [row["stage"] for row in comparison["stage_offsets"]],
            ["bud_burst", "full_bloom", "fruit_set", "harvest"],
        )
        # 右侧减左侧的确定性偏移：3/15-3/10=5，4/5-4/1=4，
        # 4/22-4/18=4，9/7-9/2=5。
        self.assertEqual(
            [row["offset_days"] for row in comparison["stage_offsets"]],
            [5, 4, 4, 5],
        )
        status, listing = self.api("GET", "/comparisons")
        self.assertEqual(listing["total"], 1)

    # --- 对象修订冲突 ---------------------------------------------------

    def test_stale_revision_returns_409(self) -> None:
        _, plot = self.api("PUT", "/plots", plot_payload("OR-5624"))
        status, newer = self.api(
            "PATCH",
            f"/plots/{plot['id']}",
            {"name": "已更新名称", "revision": plot["revision"]},
        )
        self.assertEqual(status, 200, newer)
        status, payload = self.api(
            "PATCH",
            f"/plots/{plot['id']}",
            {"name": "过期写入", "revision": plot["revision"]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "revision_conflict")
        self.assertEqual(payload["error"]["details"]["actual"], 2)
        status, reloaded = self.api("GET", f"/plots/{plot['id']}")
        self.assertEqual(reloaded["name"], "已更新名称")

    # --- 幂等：重复请求不产生额外事实 -----------------------------------

    def test_idempotent_retry_does_not_create_extra_fact(self) -> None:
        body = plot_payload("OR-5625")
        first_status, first = self.api("PUT", "/plots", body, key="http-retry")
        second_status, second = self.api("PUT", "/plots", body, key="http-retry")
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first["id"], second["id"])
        status, listing = self.api("GET", "/plots")
        self.assertEqual(listing["total"], 1)
        status, audit = http_request(
            self.base,
            "GET",
            f"/audit?resource_id={first['id']}",
            actor="local-admin",
        )
        self.assertEqual(audit["total"], 1)

    def test_same_idempotency_key_different_body_returns_409(self) -> None:
        self.api("PUT", "/plots", plot_payload("OR-5626"), key="shared-http-key")
        status, payload = self.api(
            "PUT", "/plots", plot_payload("OR-5627"), key="shared-http-key"
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_key_reused")
        status, listing = self.api("GET", "/plots")
        self.assertEqual(listing["total"], 1)

    # --- 对抗场景一：同一操作并发提交 -----------------------------------

    @unittest.expectedFailure
    def test_concurrent_identical_creates_yield_single_fact(self) -> None:
        # 已知实现缺陷 F-001：ensure_unique_plot_code 与 ensure_unique_tree_code
        # 都以位置参数 + code= 关键字参数构造 ConflictError，负方请求实际抛
        # TypeError 并返回 500，而非规格要求的 409 plot_code_exists。
        # 事务本身已正确串行化（只落一条事实），修复错误构造后本用例即通过。
        body = plot_payload("OR-5628")

        def fire(index: int) -> tuple[int, dict[str, Any]]:
            # 不使用幂等键：两个完全相同的“建园”请求同时打进来，
            # 园区编号唯一约束必须保证只产生一条事实。
            return http_request(
                self.base, "PUT", "/plots", body, idempotency_key=f"race-{index}"
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(fire, range(2)))
        statuses = sorted(status for status, _ in results)
        self.assertEqual(statuses[0], 200, results)
        self.assertEqual(statuses[1], 409, results)
        codes = {payload["error"]["code"] for status, payload in results if status == 409}
        self.assertEqual(codes, {"plot_code_exists"})
        status, listing = self.api("GET", "/plots")
        self.assertEqual(listing["total"], 1)

    def test_concurrent_stage_adds_with_same_revision_only_one_persists(self) -> None:
        _, tree = self.create_draft_plot_with_tree("OR-5629")
        _, observation = self.api(
            "PUT", "/observations", observation_payload(tree["id"])
        )
        body = stage_payload("bud_burst", "2026-03-14", observation["revision"])

        def fire(index: int) -> tuple[int, dict[str, Any]]:
            return http_request(
                self.base,
                "PUT",
                f"/observations/{observation['id']}/stages",
                body,
                idempotency_key=f"stage-race-{index}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(fire, range(2)))
        # 恰好一个成功、一个冲突，不依赖线程实际先后顺序。
        self.assertEqual(sorted(status for status, _ in results), [200, 409], results)
        # 负方要么撞上乐观修订号，要么撞上“同阶段已存在”，二者都说明
        # 并发写入被正确串行化，且都不能落第二条事实。
        loser = next(payload for status, payload in results if status == 409)
        self.assertIn(
            loser["error"]["code"], {"revision_conflict", "stage_exists"}
        )
        status, detail = self.api(
            "GET", f"/observations/{observation['id']}"
        )
        self.assertEqual(len(detail["entries"]), 1)
        self.assertEqual(detail["entries"][0]["stage"], "bud_burst")

    # --- 身份与授权 -----------------------------------------------------

    def test_write_without_actor_is_unauthorized(self) -> None:
        status, payload = self.api(
            "PUT", "/plots", plot_payload("OR-5630"), actor=""
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "authentication_required")

    def test_observer_without_write_grant_is_forbidden(self) -> None:
        status, payload = self.api(
            "PUT", "/plots", plot_payload("OR-5631"), actor="local-observer"
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")


if __name__ == "__main__":
    unittest.main()
