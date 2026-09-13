#!/usr/bin/env python3
"""从仓库根目录启动后端服务。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.transport.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
