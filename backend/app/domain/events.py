"""用例声明的业务事实与事务结果。

每个写用例在事务内返回一个 :class:`Mutation`，明确说明本次提交
产生了哪些业务事实（:class:`DomainEvent`）。仓储只负责把声明过的
事实如实写入事件日志，不再根据返回对象的标识或状态字段反推。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """一条待记入快照日志的业务事实。"""

    action: str
    resource: str
    identifier: str


@dataclass(frozen=True, slots=True)
class Mutation(Generic[T]):
    """事务动作的结果：返回给调用方的对象与产生的业务事实。"""

    result: T
    events: tuple[DomainEvent, ...]


def _event(action: str, resource: str, identifier: str) -> DomainEvent:
    return DomainEvent(action=action, resource=resource, identifier=identifier)


def plot_registered(identifier: str) -> DomainEvent:
    return _event("write", "plot", identifier)


def plot_updated(identifier: str) -> DomainEvent:
    return _event("write", "plot", identifier)


def plot_confirmed(identifier: str) -> DomainEvent:
    return _event("confirm", "plot", identifier)


def tree_registered(identifier: str) -> DomainEvent:
    return _event("write", "tree", identifier)


def tree_closed(identifier: str) -> DomainEvent:
    return _event("write", "tree", identifier)


def season_started(identifier: str) -> DomainEvent:
    return _event("write", "observation", identifier)


def season_updated(identifier: str) -> DomainEvent:
    return _event("write", "observation", identifier)


def stage_recorded(identifier: str) -> DomainEvent:
    return _event("write", "observation", identifier)


def stage_removed(identifier: str) -> DomainEvent:
    return _event("write", "observation", identifier)


def season_completed(identifier: str) -> DomainEvent:
    return _event("complete", "observation", identifier)


def comparison_recorded(identifier: str) -> DomainEvent:
    return _event("write", "comparison", identifier)


def brief_frozen(identifier: str) -> DomainEvent:
    return _event("write", "brief", identifier)
