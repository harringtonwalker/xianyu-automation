from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xianyu_ops.policy import canonical_fingerprint, normalize_source
from xianyu_ops.store import Store, StoreError


def source() -> dict:
    return normalize_source(
        {
            "source_type": "local",
            "external_id": "SKU-001",
            "title": "门店小程序定制服务",
            "facts": {"交付": "源码和后台"},
            "price": "1999",
            "original_price": "2999",
            "delivery": "无需邮寄",
            "rights_confirmed": True,
        }
    )


class StoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "automation.db")
        self.cover_path = Path(self.temp.name) / "cover.png"
        self.cover_path.write_bytes(b"test-image")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def import_job(self) -> str:
        normalized = source()
        job_id, created, reason = self.store.import_source(normalized, canonical_fingerprint(normalized))
        self.assertTrue(created, reason)
        return job_id

    def generate(self, job_id: str) -> None:
        self.store.mark_generated(
            job_id,
            "门店小程序定制服务\n【商品详情】\n• 交付：源码和后台\n请在下单前确认功能范围。",
            "deterministic",
            [str(self.cover_path)],
            {"passed": True, "errors": [], "warnings": []},
        )

    def review(self, job_id: str) -> None:
        self.store.review(job_id, "确认已核对完整文案与商品事实")

    def test_duplicate_import_is_skipped(self) -> None:
        normalized = source()
        first_id, created, _ = self.store.import_source(normalized, canonical_fingerprint(normalized))
        second_id, second_created, reason = self.store.import_source(normalized, canonical_fingerprint(normalized))
        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(reason, "duplicate")
        self.assertEqual(first_id, second_id)

    def test_changed_inventory_creates_revision_and_supersedes_old_job(self) -> None:
        original = source()
        old_job, created, _ = self.store.import_source(original, canonical_fingerprint(original))
        self.assertTrue(created)
        self.generate(old_job)
        self.review(old_job)
        self.store.approve([old_job], "确认发布1条")
        changed = dict(original)
        changed["price"] = "2299.00"
        changed["facts"] = {**original["facts"], "版本": "更新后的交付范围"}
        new_job, new_created, reason = self.store.import_source(changed, canonical_fingerprint(changed))
        self.assertTrue(new_created)
        self.assertEqual(reason, "revision")
        self.assertNotEqual(new_job, old_job)
        self.assertEqual(self.store.get_job(old_job)["status"], "SUPERSEDED")
        self.assertEqual(self.store.get_job(new_job)["price"], "2299.00")
        self.assertEqual(self.store.get_job(new_job)["status"], "INGESTED")

    def test_transaction_term_and_note_changes_each_create_a_revision(self) -> None:
        variants = [
            {"delivery": "包邮"},
            {"original_price": "3999.00"},
            {"notes": "买家下单前请确认交付范围"},
        ]
        for index, change in enumerate(variants):
            with self.subTest(change=change):
                temp = tempfile.TemporaryDirectory()
                try:
                    store = Store(Path(temp.name) / "automation.db")
                    original = source()
                    old_job, _, _ = store.import_source(original, canonical_fingerprint(original))
                    changed = {**original, **change}
                    new_job, created, reason = store.import_source(
                        changed, canonical_fingerprint(changed)
                    )
                    self.assertTrue(created)
                    self.assertEqual(reason, "revision")
                    self.assertNotEqual(new_job, old_job)
                    self.assertEqual(store.get_job(old_job)["status"], "SUPERSEDED")
                finally:
                    temp.cleanup()

    def test_revision_can_return_to_a_historical_fingerprint(self) -> None:
        version_a = source()
        job_a, _, _ = self.store.import_source(
            version_a, canonical_fingerprint(version_a)
        )
        version_b = {**version_a, "price": "2299.00"}
        job_b, created_b, reason_b = self.store.import_source(
            version_b, canonical_fingerprint(version_b)
        )
        self.assertTrue(created_b)
        self.assertEqual(reason_b, "revision")
        self.assertEqual(self.store.get_job(job_a)["status"], "SUPERSEDED")

        job_a2, created_a2, reason_a2 = self.store.import_source(
            version_a, canonical_fingerprint(version_a)
        )
        self.assertTrue(created_a2)
        self.assertEqual(reason_a2, "revision")
        self.assertNotEqual(job_a2, job_a)
        self.assertEqual(self.store.get_job(job_b)["status"], "SUPERSEDED")
        current = self.store.get_job(job_a2)
        self.assertEqual(current["status"], "INGESTED")
        self.assertEqual(current["price"], "1999.00")

        duplicate_id, duplicate_created, duplicate_reason = self.store.import_source(
            version_a, canonical_fingerprint(version_a)
        )
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate_reason, "duplicate")
        self.assertEqual(duplicate_id, job_a2)

    def test_inventory_update_is_blocked_during_active_execution(self) -> None:
        original = source()
        old_job, _, _ = self.store.import_source(original, canonical_fingerprint(original))
        self.generate(old_job)
        self.review(old_job)
        self.store.approve([old_job], "确认发布1条")
        self.store.lease_next(180, 3)
        changed = dict(original)
        changed["price"] = "2299.00"
        with self.assertRaisesRegex(StoreError, "禁止更新来源"):
            self.store.import_source(changed, canonical_fingerprint(changed))

    def test_approval_lease_and_receipt(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        with self.assertRaisesRegex(StoreError, "确认文字"):
            self.store.approve([job_id], "确认")
        self.store.approve([job_id], "确认发布1条")
        leased = self.store.lease_next(lease_seconds=180, max_attempts=3)
        self.assertEqual(leased["id"], job_id)
        self.assertEqual(leased["status"], "RUNNING")
        self.store.report(job_id, leased["lease_token"], "filled", {"image_count": 3})
        self.store.report(job_id, leased["lease_token"], "submitting", {})
        self.assertEqual(self.store.get_job(job_id)["status"], "AWAITING_RECEIPT")
        self.store.report(
            job_id,
            leased["lease_token"],
            "published",
            {"receipt_url": "https://www.goofish.com/item?id=123456", "item_id": "123456"},
        )
        finished = self.store.get_job(job_id)
        self.assertEqual(finished["status"], "PUBLISHED")
        self.assertEqual(finished["receipt_item_id"], "123456")

    def test_invalid_receipt_does_not_mark_published(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.store.approve([job_id], "确认发布1条")
        leased = self.store.lease_next(180, 3)
        self.store.report(job_id, leased["lease_token"], "submitting", {})
        with self.assertRaisesRegex(StoreError, "回执"):
            self.store.report(job_id, leased["lease_token"], "published", {"receipt_url": "https://example.com", "item_id": "123456"})
        self.assertEqual(self.store.get_job(job_id)["status"], "AWAITING_RECEIPT")

    def test_published_requires_submitting_transition(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.store.approve([job_id], "确认发布1条")
        leased = self.store.lease_next(180, 3)
        with self.assertRaisesRegex(StoreError, "不能报告 published"):
            self.store.report(
                job_id,
                leased["lease_token"],
                "published",
                {
                    "receipt_url": "https://www.goofish.com/item?id=123456",
                    "item_id": "123456",
                },
            )
        self.assertEqual(self.store.get_job(job_id)["status"], "RUNNING")

    def test_receipt_item_id_is_unique_across_jobs(self) -> None:
        first_job = self.import_job()
        self.generate(first_job)
        self.review(first_job)
        self.store.approve([first_job], "确认发布1条")
        first_lease = self.store.lease_next(180, 3)
        self.store.report(first_job, first_lease["lease_token"], "submitting", {})
        self.store.report(
            first_job,
            first_lease["lease_token"],
            "published",
            {
                "receipt_url": "https://www.goofish.com/item?id=123456",
                "item_id": "123456",
            },
        )

        second_source = source()
        second_source["external_id"] = "SKU-002"
        second_job, _, _ = self.store.import_source(
            second_source, canonical_fingerprint(second_source)
        )
        self.generate(second_job)
        self.review(second_job)
        self.store.approve([second_job], "确认发布1条")
        second_lease = self.store.lease_next(180, 3)
        self.store.report(second_job, second_lease["lease_token"], "submitting", {})
        with self.assertRaisesRegex(StoreError, "已归属于其他任务"):
            self.store.report(
                second_job,
                second_lease["lease_token"],
                "published",
                {
                    "receipt_url": "https://www.goofish.com/item?id=123456",
                    "item_id": "123456",
                },
            )
        self.assertEqual(self.store.get_job(second_job)["status"], "AWAITING_RECEIPT")

    def test_expired_pre_submit_lease_recovers(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.store.approve([job_id], "确认发布1条")
        self.store.lease_next(180, 3)
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET lease_until = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job_id,))
        result = self.store.recover_expired(3)
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(self.store.get_job(job_id)["status"], "APPROVED")

    def test_awaiting_receipt_never_auto_retries(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.store.approve([job_id], "确认发布1条")
        leased = self.store.lease_next(180, 3)
        self.store.report(job_id, leased["lease_token"], "submitting", {})
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET lease_until = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job_id,))
        self.store.recover_expired(3)
        self.assertEqual(self.store.get_job(job_id)["status"], "AWAITING_RECEIPT")

    def test_approval_requires_full_content_review(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        with self.assertRaisesRegex(StoreError, "完整内容复核"):
            self.store.approve([job_id], "确认发布1条")

    def test_review_hash_detects_image_tampering(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.cover_path.write_bytes(b"changed-after-review")
        with self.assertRaisesRegex(StoreError, "完整内容复核"):
            self.store.approve([job_id], "确认发布1条")

    def test_forged_or_mismatched_receipts_are_rejected(self) -> None:
        for receipt_url, item_id in [
            ("https://evil.example/path/goofish.com/item?id=123456", "123456"),
            ("https://www.goofish.com/item?id=123456", "999999"),
            ("https://www.goofish.com/item?id=", "123456"),
        ]:
            with self.subTest(receipt_url=receipt_url, item_id=item_id):
                temp = tempfile.TemporaryDirectory()
                try:
                    store = Store(Path(temp.name) / "automation.db")
                    cover_path = Path(temp.name) / "cover.png"
                    cover_path.write_bytes(b"test-image")
                    normalized = source()
                    job_id, _, _ = store.import_source(normalized, canonical_fingerprint(normalized))
                    store.mark_generated(
                        job_id,
                        "门店小程序定制服务\n【商品详情】\n• 交付：源码和后台\n请在下单前确认功能范围。",
                        "deterministic",
                        [str(cover_path)],
                        {"passed": True, "errors": [], "warnings": []},
                    )
                    store.review(job_id, "确认已核对完整文案与商品事实")
                    store.approve([job_id], "确认发布1条")
                    leased = store.lease_next(180, 3)
                    store.report(job_id, leased["lease_token"], "submitting", {})
                    with self.assertRaisesRegex(StoreError, "回执"):
                        store.report(
                            job_id,
                            leased["lease_token"],
                            "published",
                            {"receipt_url": receipt_url, "item_id": item_id},
                        )
                    self.assertEqual(store.get_job(job_id)["status"], "AWAITING_RECEIPT")
                finally:
                    temp.cleanup()

    def test_uncertain_receipt_cannot_directly_retry(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        self.store.approve([job_id], "确认发布1条")
        leased = self.store.lease_next(180, 3)
        self.store.report(job_id, leased["lease_token"], "submitting", {})
        self.store.report(
            job_id,
            leased["lease_token"],
            "blocked",
            {"code": "RECEIPT_UNCERTAIN", "message": "timeout"},
        )
        with self.assertRaisesRegex(StoreError, "必须先对账"):
            self.store.retry(job_id, "确认重新排队")
        self.store.reconcile(job_id, "verified_not_published", "确认未发布并重新排队")
        reconciled = self.store.get_job(job_id)
        self.assertEqual(reconciled["status"], "PENDING_APPROVAL")
        self.assertEqual(reconciled["attempt_count"], 0)

    def test_manual_retry_resets_exhausted_attempts(self) -> None:
        job_id = self.import_job()
        self.generate(job_id)
        self.review(job_id)
        with self.store.connect() as db:
            db.execute(
                """
                UPDATE jobs SET status = 'FAILED', attempt_count = 3,
                    error_code = 'LEASE_EXHAUSTED', error_message = 'stopped' WHERE id = ?
                """,
                (job_id,),
            )
        self.store.retry(job_id, "确认重新排队")
        reset = self.store.get_job(job_id)
        self.assertEqual(reset["attempt_count"], 0)
        self.store.approve([job_id], "确认发布1条")
        self.assertIsNotNone(self.store.lease_next(180, 3))


if __name__ == "__main__":
    unittest.main()
