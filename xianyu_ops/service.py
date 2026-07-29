from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from .config import (
    ensure_config,
    force_disable_publisher,
    load_private_config,
    set_publisher_enabled,
    update_public_config,
)
from .content import generate_description
from .imaging import render_listing_images
from .policy import PolicyError, canonical_fingerprint, normalize_source, quality_check
from .store import Store, StoreError


class OperationsService:
    def __init__(self, data_dir: Path, base_url: str):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._harden_existing_data_tree()
        self.base_url = base_url.rstrip("/")
        self.public_config, self.extension_token = ensure_config(self.data_dir)
        self.store = Store(self.data_dir / "automation.db")

    def _harden_existing_data_tree(self) -> None:
        if self.data_dir.is_symlink():
            raise ValueError("data-dir 不允许是符号链接")
        for root, dirs, files in os.walk(self.data_dir, followlinks=False):
            root_path = Path(root)
            os.chmod(root_path, 0o700)
            for name in dirs:
                path = root_path / name
                if not path.is_symlink():
                    os.chmod(path, 0o700)
            for name in files:
                path = root_path / name
                if not path.is_symlink():
                    os.chmod(path, 0o600)

    def refresh_config(self) -> dict[str, Any]:
        self.public_config, self.extension_token = ensure_config(self.data_dir)
        return self.public_config

    def health(self) -> dict[str, Any]:
        jobs = self.store.list_jobs()
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return {
            "ok": True,
            "service": "xianyu-ops",
            "version": "1.0.0",
            "publisher_enabled": bool(self.refresh_config()["publisher_enabled"]),
            "platform_contract": "goofish-web-publish-2026-07-28",
            "counts": counts,
        }

    def import_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if len(records) > 1000:
            raise PolicyError("单次最多导入 1000 条")
        imported: list[str] = []
        duplicates: list[str] = []
        errors: list[dict[str, Any]] = []
        for index, raw in enumerate(records):
            try:
                if not isinstance(raw, dict):
                    raise PolicyError("每条 record 必须是 JSON 对象")
                source = normalize_source(raw)
                fingerprint = canonical_fingerprint(source)
                job_id, created, reason = self.store.import_source(source, fingerprint)
                if created:
                    imported.append(job_id)
                elif reason == "duplicate":
                    duplicates.append(job_id)
            except (PolicyError, StoreError, ValueError) as exc:
                errors.append({"index": index, "error": str(exc)})
        return {"imported": imported, "duplicates": duplicates, "errors": errors}

    def import_csv(self, text: str) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        records: list[dict[str, Any]] = []
        for row in reader:
            facts: dict[str, str] = {}
            facts_json = (row.get("facts_json") or "").strip()
            if facts_json:
                try:
                    parsed = json.loads(facts_json)
                    if isinstance(parsed, dict):
                        facts = parsed
                except json.JSONDecodeError as exc:
                    raise PolicyError(f"facts_json 不是有效 JSON：{exc}") from None
            for key, value in row.items():
                if key.startswith("fact_") and value:
                    facts[key.removeprefix("fact_")] = value
            records.append(
                {
                    **row,
                    "facts": facts,
                    "rights_confirmed": str(row.get("rights_confirmed") or "").strip().lower()
                    in {"true", "1", "yes", "是"},
                }
            )
        return self.import_records(records)

    def generate_job(self, job_id: str) -> dict[str, Any]:
        source = self.store.source_for_job(job_id)
        config = self.refresh_config()
        description, content_mode = generate_description(source, config["brand_name"])
        quality = quality_check(source, description)
        if not quality["passed"]:
            raise PolicyError("；".join(quality["errors"]))
        output_dir = self.data_dir / "assets" / job_id
        image_paths = render_listing_images(source, output_dir, config["watermark_text"])
        self.store.mark_generated(job_id, description, content_mode, image_paths, quality)
        return self.public_job(self.store.get_job(job_id))

    def generate_all(self) -> dict[str, Any]:
        generated: list[str] = []
        errors: list[dict[str, str]] = []
        for job in self.store.list_jobs():
            if job["status"] != "INGESTED":
                continue
            try:
                self.generate_job(job["id"])
                generated.append(job["id"])
            except Exception as exc:
                errors.append({"job_id": job["id"], "error": str(exc)})
        return {"generated": generated, "errors": errors}

    def list_jobs(self) -> list[dict[str, Any]]:
        return [self.public_job(job) for job in self.store.list_jobs()]

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.public_job(self.store.get_job(job_id))

    def public_job(self, job: dict[str, Any]) -> dict[str, Any]:
        safe = dict(job)
        safe["image_urls"] = [
            f"{self.base_url}/api/assets/{job['id']}/{Path(path).name}"
            for path in job.get("image_paths", [])
        ]
        safe.pop("image_paths", None)
        safe.pop("review_hash", None)
        return safe

    def review(self, job_id: str, acknowledgement: str) -> dict[str, Any]:
        return self.public_job(self.store.review(job_id, acknowledgement))

    def approve(self, job_ids: list[str], acknowledgement: str) -> dict[str, Any]:
        return {"approved": self.store.approve(job_ids, acknowledgement)}

    def set_publisher(self, enabled: bool, acknowledgement: str) -> dict[str, Any]:
        set_publisher_enabled(self.data_dir, enabled, acknowledgement)
        return {"publisher_enabled": enabled}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        result = update_public_config(self.data_dir, changes)
        self.refresh_config()
        return result

    def pairing_token(self) -> dict[str, str]:
        private = load_private_config(self.data_dir)
        return {"extension_token": private["extension_token"], "server_url": self.base_url}

    def lease_next(self) -> dict[str, Any]:
        config = self.refresh_config()
        self.store.recover_expired(int(config["max_publish_attempts"]))
        blocker = self.store.queue_blocker()
        if blocker:
            return {
                "job": None,
                "publisher_enabled": bool(config["publisher_enabled"]),
                "queue_blocked": blocker,
            }
        if not config["publisher_enabled"]:
            return {"job": None, "publisher_enabled": False}
        job = self.store.lease_next(
            lease_seconds=int(config["lease_seconds"]),
            max_attempts=int(config["max_publish_attempts"]),
        )
        if not job:
            return {"job": None, "publisher_enabled": True}
        public = self.public_job(job)
        public["execution_mode"] = "submit"
        public["platform_contract"] = "goofish-web-publish-2026-07-28"
        public["location_mode"] = config["default_location_mode"]
        return {"job": public, "publisher_enabled": True}

    def report(self, job_id: str, lease_token: str, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.store.report(job_id, lease_token, stage, payload)
        # Every blocked state is a global circuit-breaker. Risk prompts, DOM
        # drift, wrong pages, and uncertain receipts must stop the whole queue,
        # not merely the current job.
        if stage.lower() == "blocked":
            force_disable_publisher(self.data_dir)
            self.refresh_config()
        return self.public_job(job)

    def reconcile(
        self,
        job_id: str,
        decision: str,
        acknowledgement: str,
        receipt_url: str = "",
        item_id: str = "",
    ) -> dict[str, Any]:
        return self.public_job(
            self.store.reconcile(job_id, decision, acknowledgement, receipt_url, item_id)
        )

    def asset_path(self, job_id: str, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise FileNotFoundError
        path = (self.data_dir / "assets" / job_id / filename).resolve()
        root = (self.data_dir / "assets").resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError
        return path
