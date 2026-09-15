"""HTTP 服务生命周期入口。"""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

from ..config import parse_args
from ..persistence import Database, Repository
from .server import create_server


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = parse_args(argv)
    repository = Repository(
        Database(config.database_path),
        legacy_state_path=config.legacy_state_path,
    )
    repository.open()
    server = create_server(config, repository)
    stopping = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    logging.getLogger("orchard-phenology-atlas").info(
        "服务启动：http://%s:%s，数据目录 %s",
        config.host,
        config.port,
        config.data_dir,
    )
    try:
        server.serve_forever(0.25)
    finally:
        server.server_close()
        repository.close()
        logging.getLogger("orchard-phenology-atlas").info("服务已停止")
    return 0
