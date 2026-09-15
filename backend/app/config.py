"""服务运行参数。"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    host: str
    port: int
    data_dir: Path
    request_limit: int
    max_workers: int

    @property
    def database_path(self) -> Path:
        return self.data_dir / "atlas.sqlite3"

    @property
    def legacy_state_path(self) -> Path:
        return self.data_dir / "state.json"

def _bounded_int(value: str, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} 必须是整数") from exc
    if parsed < minimum or parsed > maximum:
        raise argparse.ArgumentTypeError(
            f"{label} 必须在 {minimum} 到 {maximum} 之间"
        )
    return parsed


def parse_args(argv: list[str] | None = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(description="果园物候图谱 HTTP 服务")
    parser.add_argument(
        "--host",
        default=os.getenv("ORCHARD_ATLAS_HOST", "127.0.0.1"),
        help="监听地址，默认仅本机",
    )
    parser.add_argument(
        "--port",
        type=lambda value: _bounded_int(value, 1, 65535, "端口"),
        default=int(os.getenv("ORCHARD_ATLAS_PORT", "8765")),
        help="监听端口",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.getenv(
                "ORCHARD_ATLAS_DATA_DIR",
                str(Path(__file__).resolve().parents[1] / "var"),
            )
        ),
        help="SQLite 数据库与运行文件目录",
    )
    parser.add_argument(
        "--request-limit",
        type=lambda value: _bounded_int(value, 4096, 8_388_608, "请求上限"),
        default=1_048_576,
        help="单次 JSON 请求最大字节数",
    )
    parser.add_argument(
        "--max-workers",
        type=lambda value: _bounded_int(value, 1, 64, "工作线程数"),
        default=8,
        help="HTTP 工作线程数量",
    )
    args = parser.parse_args(argv)
    return RuntimeConfig(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir.resolve(),
        request_limit=args.request_limit,
        max_workers=args.max_workers,
    )
