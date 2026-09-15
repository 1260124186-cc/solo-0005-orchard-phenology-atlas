from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.application import CatalogService
from app.errors import ConflictError, DomainError
from app.jobs import JobService
from app.persistence import Database, Repository
from app.security import (
    AuthorizationService,
    IdentityService,
    RequestContext,
    request_scope,
)


class RepositoryFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = Database(self.data_dir / "atlas.sqlite3")
        self.repository = Repository(self.database)
        self.repository.open()
        self.catalog = CatalogService(self.repository)

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_idempotency_key_reuses_response_and_revision(self) -> None:
        payload = self._plot_payload("OR-6101")
        request_hash = f"{payload['code']}:{payload['name']}"
        with _request("local-admin", "same-key", request_hash=request_hash):
            first = self.catalog.create_plot(payload)
            revision_after_first = self.repository.read()["revision"]
            second = self.catalog.create_plot(payload)
            revision_after_second = self.repository.read()["revision"]

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(revision_after_first, revision_after_second)
        self.assertEqual(len(self.repository.read()["plots"]), 1)

    def test_idempotency_key_rejects_different_payload(self) -> None:
        first = self._plot_payload("OR-6102")
        second = self._plot_payload("OR-6103")
        with _request(
            "local-admin",
            "shared-key",
            request_hash=f"{first['code']}:{first['name']}",
        ):
            self.catalog.create_plot(first)
            with self.assertRaises(ConflictError) as raised:
                with _request(
                    "local-admin",
                    "shared-key",
                    request_hash=f"{second['code']}:{second['name']}",
                ):
                    self.catalog.create_plot(second)
        self.assertEqual(raised.exception.code, "idempotency_key_reused")

    def test_object_versions_and_audit_are_committed_together(self) -> None:
        with _request("local-admin", "create-plot"):
            plot = self.catalog.create_plot(self._plot_payload("OR-6104"))
        with _request("local-admin", "update-plot"):
            self.catalog.update_plot(
                plot["id"],
                {
                    "name": "更新后的园区",
                    "revision": plot["revision"],
                },
            )

        versions = self.repository.list_entity_versions(
            kind="plot",
            identifier=plot["id"],
        )
        audit = self.repository.list_audit_events(
            resource_kind="plot",
            resource_id=plot["id"],
        )
        self.assertEqual([item["revision"] for item in versions["items"]], [2, 1])
        self.assertEqual(audit["total"], 2)
        self.assertEqual(audit["items"][0]["actor_id"], "local-admin")

    def test_authorization_supports_wildcards_and_scopes(self) -> None:
        authorization = AuthorizationService(self.database)
        authorization.require(
            actor_id="local-admin",
            capability="anything:write",
            resource_kind="anything",
            resource_id="one",
        )
        authorization.require(
            actor_id="local-observer",
            capability="plot:read",
            resource_kind="plot",
            resource_id="any-plot",
        )
        with self.assertRaises(DomainError) as raised:
            authorization.require(
                actor_id="local-observer",
                capability="plot:write",
                resource_kind="plot",
                resource_id="any-plot",
            )
        self.assertEqual(raised.exception.code, "forbidden")

    def test_identity_and_scope_revocation_are_enforced(self) -> None:
        identity = IdentityService(self.database)
        identity.create_actor(actor_id="observer-a", display_name="观察员甲")
        grant = identity.grant(
            actor_id="observer-a",
            capability="plot:read",
            resource_kind="plot",
            resource_id="plot-one",
        )
        authorization = AuthorizationService(self.database)
        authorization.require(
            actor_id="observer-a",
            capability="plot:read",
            resource_kind="plot",
            resource_id="plot-one",
        )
        with self.assertRaises(DomainError) as raised:
            authorization.require(
                actor_id="observer-a",
                capability="plot:read",
                resource_kind="plot",
                resource_id="plot-two",
            )
        self.assertEqual(raised.exception.code, "forbidden")

        identity.revoke(grant["id"])
        with self.assertRaises(DomainError) as raised:
            authorization.require(
                actor_id="observer-a",
                capability="plot:read",
                resource_kind="plot",
                resource_id="plot-one",
            )
        self.assertEqual(raised.exception.code, "forbidden")
        audit = self.repository.list_audit_events(resource_kind="grant")
        self.assertEqual(audit["total"], 2)
        self.assertGreaterEqual(self.repository.read()["revision"], 3)

    def test_concurrent_writers_do_not_lose_updates(self) -> None:
        def create(index: int) -> str:
            with _request("local-admin", f"concurrent-{index}"):
                return self.catalog.create_plot(
                    self._plot_payload(f"OR-{7100 + index}")
                )["id"]

        with ThreadPoolExecutor(max_workers=6) as executor:
            identifiers = list(executor.map(create, range(12)))

        state = self.repository.read()
        self.assertEqual(len(set(identifiers)), 12)
        self.assertEqual(len(state["plots"]), 12)
        self.assertGreaterEqual(state["revision"], 12)

    def _plot_payload(self, code: str) -> dict[str, object]:
        return {
            "code": code,
            "name": f"测试园区 {code}",
            "locality": "测试地点",
            "cultivar_focus": "测试品种",
            "steward": "测试组",
            "planting_year": 2010,
            "note": "",
        }


class JobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary.name) / "atlas.sqlite3")
        self.database.initialize()
        self.jobs = JobService(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_job_lifecycle_and_idempotent_enqueue(self) -> None:
        first = self.jobs.enqueue(
            actor_id="local-admin",
            job_type="integrity_scan",
            payload={},
            idempotency_key="job-key",
        )
        second = self.jobs.enqueue(
            actor_id="local-admin",
            job_type="integrity_scan",
            payload={},
            idempotency_key="job-key",
        )
        self.assertEqual(first["id"], second["id"])

        claimed = self.jobs.claim(worker_id="worker-a", lease_seconds=30)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["attempt"], 1)
        completed = self.jobs.complete(
            claimed["id"],
            worker_id="worker-a",
            result={"status": "healthy"},
        )
        self.assertEqual(completed["status"], "succeeded")

    def test_failed_job_is_requeued_until_dead_letter(self) -> None:
        job = self.jobs.enqueue(
            actor_id="local-admin",
            job_type="failing_job",
            payload={},
            max_attempts=1,
        )
        claimed = self.jobs.claim(worker_id="worker-a")
        assert claimed is not None
        failed = self.jobs.fail(
            job["id"],
            worker_id="worker-a",
            error="boom",
        )
        self.assertEqual(failed["status"], "dead_letter")
        self.assertIn("boom", failed["error"])


def _request(
    actor_id: str,
    idempotency_key: str,
    *,
    request_hash: str | None = None,
):
    return request_scope(
        RequestContext(
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_method="PUT",
            request_path="/api/test",
            request_hash=request_hash or f"{actor_id}:{idempotency_key}",
            route_template="/api/test",
        )
    )


if __name__ == "__main__":
    unittest.main()
