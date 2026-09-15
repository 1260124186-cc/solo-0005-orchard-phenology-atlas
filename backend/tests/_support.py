"""业务回归测试公共工具。

这些测试刻意走与生产相同的技术栈：

* 真实的 SQLite 文件数据库（临时目录，每个用例独立）；
* 真实的 ``Repository`` 事务、对象版本与幂等上下文；
* 真实的标准库 HTTP 服务（``test_http_business.py``）。

测试中的预期全部来自 ``PROJECT_SPEC.md`` 的业务规则，而不是当前输出的快照。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from app.persistence import Database, Repository
from app.security import RequestContext, request_scope



def plot_payload(code: str = "OR-5001", **overrides: Any) -> dict[str, Any]:
    payload = {
        "code": code,
        "name": f"测试园区 {code}",
        "locality": "河湾村北坡",
        "cultivar_focus": "黄皮秋梨",
        "steward": "县物候档案组",
        "planting_year": 2010,
        "note": "",
    }
    payload.update(overrides)
    return payload


def tree_payload(
    plot_id: str,
    code: str = "OR-5001-T01",
    **overrides: Any,
) -> dict[str, Any]:
    payload = {
        "plot_id": plot_id,
        "code": code,
        "cultivar": "黄皮秋梨",
        "rootstock": "杜梨",
        "planting_year": 2012,
        "status": "active",
        "note": "",
    }
    payload.update(overrides)
    return payload


def observation_payload(tree_id: str, season: str = "2026", **overrides: Any) -> dict[str, Any]:
    payload = {
        "tree_id": tree_id,
        "season": season,
        "observer": "周岚",
        "note": "",
    }
    payload.update(overrides)
    return payload


def stage_payload(
    stage: str,
    observed_on: str,
    revision: int,
    *,
    confidence: int = 4,
    note: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "observed_on": observed_on,
        "confidence": confidence,
        "note": note,
        "revision": revision,
    }


REQUIRED_STAGE_DATES_2026 = {
    "bud_burst": "2026-03-14",
    "full_bloom": "2026-04-06",
    "fruit_set": "2026-04-24",
    "harvest": "2026-09-08",
}


@contextmanager
def request_context(
    actor_id: str = "local-admin",
    idempotency_key: str | None = None,
    *,
    method: str = "PUT",
    path: str = "/api/test",
    request_hash: str | None = None,
) -> Iterator[None]:
    context = RequestContext(
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        request_method=method,
        request_path=path,
        request_hash=request_hash or f"{actor_id}:{idempotency_key or 'none'}:{path}",
        route_template=path,
    )
    with request_scope(context):
        yield


class DatabaseHarness:
    """管理一个临时目录中的真实 SQLite 仓储。"""

    def __init__(self) -> None:
        self.temporary = TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = Database(self.data_dir / "atlas.sqlite3")
        self.repository = Repository(self.database)
        self.repository.open()

    def cleanup(self) -> None:
        self.repository.close()
        self.temporary.cleanup()


def http_request(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    actor: str = "local-admin",
    idempotency_key: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    request_headers = {"Content-Type": "application/json"}
    if actor:
        request_headers["X-Actor-Id"] = actor
    if idempotency_key is not None:
        request_headers["X-Idempotency-Key"] = idempotency_key
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8"))
        finally:
            error.close()
