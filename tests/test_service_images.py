from __future__ import annotations

import os
import tempfile
import stat
import unittest
from pathlib import Path

from PIL import Image

from xianyu_ops.service import OperationsService


class ServiceImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = OperationsService(Path(self.temp.name), "http://127.0.0.1:8766")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_import_generate_images_and_public_urls(self) -> None:
        result = self.service.import_records(
            [
                {
                    "source_type": "local",
                    "external_id": "CARD-001",
                    "title": "品牌门店预约小程序",
                    "facts": {"交付": "源码与后台", "服务": "需求梳理和部署说明"},
                    "price": "1999",
                    "original_price": "2999",
                    "delivery": "无需邮寄",
                    "rights_confirmed": True,
                }
            ]
        )
        self.assertEqual(len(result["imported"]), 1)
        job = self.service.generate_job(result["imported"][0])
        self.assertEqual(job["status"], "PENDING_APPROVAL")
        self.assertEqual(len(job["image_urls"]), 3)
        asset_root = Path(self.temp.name) / "assets" / job["id"]
        images = sorted(asset_root.glob("*.png"))
        self.assertEqual(len(images), 3)
        for image_path in images:
            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1080, 1080))
                self.assertEqual(image.format, "PNG")
        self.assertNotEqual(images[0].read_bytes(), images[1].read_bytes())

    def test_publisher_is_disabled_by_default(self) -> None:
        self.assertFalse(self.service.health()["publisher_enabled"])
        self.assertEqual(self.service.lease_next(), {"job": None, "publisher_enabled": False})

    def test_pairing_token_is_persistent(self) -> None:
        first = self.service.pairing_token()["extension_token"]
        second = OperationsService(Path(self.temp.name), "http://127.0.0.1:8766").pairing_token()["extension_token"]
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 32)

    def test_non_object_records_are_reported_without_crashing(self) -> None:
        result = self.service.import_records([42, "text", None])  # type: ignore[list-item]
        self.assertEqual(len(result["errors"]), 3)
        self.assertEqual(result["imported"], [])

    def test_runtime_data_database_and_assets_are_private(self) -> None:
        result = self.service.import_records(
            [
                {
                    "source_type": "local",
                    "external_id": "PRIVATE-001",
                    "title": "私有权限检查商品",
                    "facts": {"交付": "测试事实"},
                    "price": "19",
                    "delivery": "无需邮寄",
                    "rights_confirmed": True,
                }
            ]
        )
        job = self.service.generate_job(result["imported"][0])
        paths = [
            (Path(self.temp.name), 0o700),
            (Path(self.temp.name) / "automation.db", 0o600),
            (Path(self.temp.name) / "config.json", 0o600),
            (Path(self.temp.name) / "assets", 0o700),
            (Path(self.temp.name) / "assets" / job["id"], 0o700),
        ]
        paths.extend(
            (path, 0o600)
            for path in (Path(self.temp.name) / "assets" / job["id"]).glob("*.png")
        )
        for path, expected in paths:
            with self.subTest(path=path):
                mode = stat.S_IMODE(path.stat().st_mode)
                self.assertEqual(mode, expected)

        os.chmod(Path(self.temp.name), 0o755)
        os.chmod(Path(self.temp.name) / "automation.db", 0o644)
        os.chmod(Path(self.temp.name) / "assets", 0o755)
        for path in (Path(self.temp.name) / "assets").rglob("*"):
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
        OperationsService(Path(self.temp.name), "http://127.0.0.1:8766")
        self.assertEqual(stat.S_IMODE(Path(self.temp.name).stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE((Path(self.temp.name) / "automation.db").stat().st_mode),
            0o600,
        )
        for path in (Path(self.temp.name) / "assets").rglob("*"):
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                0o700 if path.is_dir() else 0o600,
            )

    def test_uncertain_receipt_forces_global_publisher_pause(self) -> None:
        result = self.service.import_records(
            [
                {
                    "source_type": "local",
                    "external_id": "PAUSE-001",
                    "title": "需要回执对账的商品",
                    "facts": {"交付": "测试事实"},
                    "price": "19",
                    "delivery": "无需邮寄",
                    "rights_confirmed": True,
                }
            ]
        )
        job_id = result["imported"][0]
        self.service.generate_job(job_id)
        self.service.review(job_id, "确认已核对完整文案与商品事实")
        self.service.approve([job_id], "确认发布1条")
        self.service.set_publisher(True, "启用自动发布")
        leased = self.service.lease_next()["job"]
        self.service.report(job_id, leased["lease_token"], "submitting", {})
        self.service.report(
            job_id,
            leased["lease_token"],
            "blocked",
            {"code": "RECEIPT_UNCERTAIN", "message": "timeout"},
        )
        self.assertFalse(self.service.health()["publisher_enabled"])
        blocked = self.service.lease_next()
        self.assertIsNone(blocked["job"])
        self.assertIn("人工对账", blocked["queue_blocked"])

    def test_any_blocked_execution_forces_global_publisher_pause(self) -> None:
        for code in ("RISK_SIGNAL", "DOM_CONTRACT_CHANGED", "WRONG_PAGE"):
            with self.subTest(code=code):
                temp = tempfile.TemporaryDirectory()
                try:
                    service = OperationsService(Path(temp.name), "http://127.0.0.1:8766")
                    result = service.import_records(
                        [
                            {
                                "source_type": "local",
                                "external_id": f"STOP-{code}-1",
                                "title": "触发全局断路器的商品",
                                "facts": {"交付": "测试事实"},
                                "price": "19",
                                "delivery": "无需邮寄",
                                "rights_confirmed": True,
                            },
                            {
                                "source_type": "local",
                                "external_id": f"STOP-{code}-2",
                                "title": "断路器后的候选商品",
                                "facts": {"交付": "测试事实二"},
                                "price": "29",
                                "delivery": "无需邮寄",
                                "rights_confirmed": True,
                            }
                        ]
                    )
                    for candidate_id in result["imported"]:
                        service.generate_job(candidate_id)
                        service.review(candidate_id, "确认已核对完整文案与商品事实")
                    service.approve(result["imported"], "确认发布2条")
                    service.set_publisher(True, "启用自动发布")
                    leased = service.lease_next()["job"]
                    job_id = leased["id"]
                    service.report(
                        job_id,
                        leased["lease_token"],
                        "blocked",
                        {"code": code, "message": "fail closed"},
                    )
                    self.assertFalse(service.health()["publisher_enabled"])
                    self.assertIsNone(service.lease_next()["job"])
                    remaining = [
                        job for job in service.list_jobs() if job["id"] != job_id
                    ]
                    self.assertEqual(remaining[0]["status"], "APPROVED")
                finally:
                    temp.cleanup()


if __name__ == "__main__":
    unittest.main()
