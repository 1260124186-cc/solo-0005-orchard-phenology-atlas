from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.config import RuntimeConfig
from app.persistence import Database, Repository
from app.transport.server import create_server


class HttpFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        data_dir = Path(self.temporary.name)
        self.repository = Repository(Database(data_dir / "atlas.sqlite3"))
        self.repository.open()
        self.server = create_server(
            RuntimeConfig(
                host="127.0.0.1",
                port=0,
                data_dir=data_dir,
                request_limit=1_048_576,
                max_workers=8,
            ),
            self.repository,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.repository.close()
        self.temporary.cleanup()

    def test_http_auth_idempotency_audit_and_jobs(self) -> None:
        status, payload = self._request("GET", "/plots")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "authentication_required")

        headers = {
            "X-Actor-Id": "local-admin",
            "X-Idempotency-Key": "http-plot-key",
        }
        body = {
            "code": "OR-8101",
            "name": "HTTP 验证园",
            "locality": "测试地",
            "cultivar_focus": "测试品种",
            "steward": "测试组",
            "planting_year": 2010,
            "note": "",
        }
        first_status, first = self._request("PUT", "/plots", body, headers)
        second_status, second = self._request("PUT", "/plots", body, headers)
        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(first["id"], second["id"])

        audit_status, audit = self._request(
            "GET",
            f"/audit?resource_id={first['id']}",
            headers={"X-Actor-Id": "local-admin"},
        )
        self.assertEqual(audit_status, 200)
        self.assertEqual(audit["total"], 1)

        outbox_status, outbox = self._request(
            "GET",
            "/outbox?status=pending",
            headers={"X-Actor-Id": "local-admin"},
        )
        self.assertEqual(outbox_status, 200)
        self.assertEqual(outbox["total"], 1)
        publish_status, published = self._request(
            "PUT",
            f"/outbox/{outbox['items'][0]['event_id']}/publish",
            {},
            {"X-Actor-Id": "local-admin"},
        )
        self.assertEqual(publish_status, 200)
        self.assertEqual(published["status"], "published")

        job_status, job = self._request(
            "PUT",
            "/jobs",
            {
                "job_type": "integrity_scan",
                "payload": {},
                "max_attempts": 3,
                "priority": 100,
                "available_at": None,
            },
            {
                "X-Actor-Id": "local-admin",
                "X-Idempotency-Key": "http-job-key",
            },
        )
        self.assertEqual(job_status, 200)
        self.assertEqual(job["status"], "queued")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()


if __name__ == "__main__":
    unittest.main()
