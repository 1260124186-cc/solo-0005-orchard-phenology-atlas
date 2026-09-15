"""受进程锁保护的原子 JSON 仓储。"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from ..domain.events import DomainEvent, Mutation
from ..errors import DomainError
from .snapshot import check_relationships, empty_state, ensure_state_shape


T = TypeVar("T")
MAX_EVENTS = 4000


class ProcessLock:
    """基于文件锁阻止两个进程共享同一数据目录。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise DomainError(
                "data_dir_locked",
                "数据目录正在被另一个服务实例使用",
                503,
                {"path": str(self.path)},
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class Repository:
    """每次事务复制内存快照，原子落盘后才提交。"""

    def __init__(self, state_path: Path, lock_path: Path) -> None:
        self.state_path = state_path
        self.lock_path = lock_path
        self._thread_lock = threading.RLock()
        self._process_lock = ProcessLock(lock_path)
        self._state = empty_state()

    def open(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._process_lock.acquire()
        try:
            if self.state_path.exists():
                self._state = self._read_state()
                problems = check_relationships(self._state)
                if problems:
                    raise DomainError(
                        "state_relationships_invalid",
                        "数据快照关系检查失败",
                        500,
                        {"problems": problems[:10]},
                    )
            else:
                self._state = empty_state()
                self._write_state(self._state)
        except Exception:
            self._process_lock.release()
            raise

    def close(self) -> None:
        self._process_lock.release()

    def read(self) -> dict[str, Any]:
        with self._thread_lock:
            return copy.deepcopy(self._state)

    def atomic_update(
        self,
        action: Callable[[dict[str, Any]], Mutation[T]],
    ) -> T:
        with self._thread_lock:
            working = copy.deepcopy(self._state)
            mutation = action(working)
            working["revision"] = int(working["revision"]) + 1
            self._journal_events(working, mutation.events)
            self._write_state(working)
            self._state = working
            return copy.deepcopy(mutation.result)

    def stats(self) -> dict[str, int]:
        state = self.read()
        return {
            "revision": int(state["revision"]),
            "plot_count": len(state["plots"]),
            "tree_count": len(state["trees"]),
            "observation_count": len(state["observations"]),
            "comparison_count": len(state["comparisons"]),
            "brief_count": len(state["briefs"]),
            "event_count": len(state["events"]),
        }

    def _read_state(self) -> dict[str, Any]:
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise DomainError(
                "state_unreadable",
                "无法读取数据快照",
                500,
                {"reason": str(exc)},
            ) from exc
        return ensure_state_shape(parsed)

    def _write_state(self, state: dict[str, Any]) -> None:
        ensure_state_shape(state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        payload = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise DomainError(
                "state_write_failed",
                "数据快照写入失败，原快照保持不变",
                500,
                {"reason": str(exc)},
            ) from exc

    @staticmethod
    def _append_event(state: dict[str, Any], result: Any) -> None:
        action = "write"
        resource = "unknown"
        identifier = ""
        if isinstance(result, dict):
            identifier = str(result.get("id") or "")
            if identifier.startswith("plot_"):
                resource = "plot"
            elif identifier.startswith("tree_"):
                resource = "tree"
            elif identifier.startswith("season_"):
                resource = "observation"
            elif identifier.startswith("atlas_"):
                resource = "comparison"
            elif identifier.startswith("brief_"):
                resource = "brief"
            if result.get("status") == "completed":
                action = "complete"
            elif result.get("status") == "confirmed":
                action = "confirm"
        state["events"].append(
            {
                "sequence": len(state["events"]) + 1,
                "action": action,
                "resource": resource,
                "id": identifier,
                "revision": int(state["revision"]) + 1,
            }
        )
        if len(state["events"]) > MAX_EVENTS:
            state["events"] = state["events"][-MAX_EVENTS:]
