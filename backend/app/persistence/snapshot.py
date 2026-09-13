"""快照结构、迁移与完整性检查。"""

from __future__ import annotations

from typing import Any

from ..errors import DomainError


CURRENT_SCHEMA_VERSION = 1


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "revision": 0,
        "plots": {},
        "trees": {},
        "observations": {},
        "comparisons": {},
        "briefs": {},
        "events": [],
    }


def ensure_state_shape(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise DomainError(
            "state_corrupt",
            "数据快照顶层不是对象",
            500,
        )
    expected_containers = (
        "plots",
        "trees",
        "observations",
        "comparisons",
        "briefs",
        "events",
    )
    if state.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise DomainError(
            "state_schema_unsupported",
            "数据快照版本不受支持",
            500,
            {"actual": state.get("schema_version")},
        )
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise DomainError("state_corrupt", "数据快照修订号无效", 500)
    for key in expected_containers:
        value = state.get(key)
        if key == "events":
            if not isinstance(value, list):
                raise DomainError("state_corrupt", f"{key} 必须是数组", 500)
            continue
        if not isinstance(value, dict):
            raise DomainError("state_corrupt", f"{key} 必须是对象", 500)
        for identifier, record in value.items():
            if not isinstance(identifier, str) or not isinstance(record, dict):
                raise DomainError("state_corrupt", f"{key} 中存在非法记录", 500)
            if record.get("id") != identifier:
                raise DomainError(
                    "state_corrupt",
                    f"{key}.{identifier} 的标识不一致",
                    500,
                )
    return state


def check_relationships(state: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for tree in state["trees"].values():
        if tree["plot_id"] not in state["plots"]:
            problems.append(f"植株 {tree['id']} 引用了不存在的园区")
    for observation in state["observations"].values():
        if observation["tree_id"] not in state["trees"]:
            problems.append(f"季节志 {observation['id']} 引用了不存在的植株")
        if observation["plot_id"] not in state["plots"]:
            problems.append(f"季节志 {observation['id']} 引用了不存在的园区")
    for comparison in state["comparisons"].values():
        if comparison["left_observation_id"] not in state["observations"]:
            problems.append(f"对比图谱 {comparison['id']} 缺少左侧季节志")
        if comparison["right_observation_id"] not in state["observations"]:
            problems.append(f"对比图谱 {comparison['id']} 缺少右侧季节志")
    for brief in state["briefs"].values():
        if brief["plot"]["id"] not in state["plots"]:
            problems.append(f"简报 {brief['id']} 引用了不存在的园区")
    return problems
