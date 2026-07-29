from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse


UTC = timezone.utc
TERMINAL_STATES = {"PUBLISHED", "BLOCKED", "FAILED"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validated_receipt(receipt_url: str, item_id: str) -> tuple[str, str]:
    receipt_url = str(receipt_url or "").strip()[:1500]
    item_id = str(item_id or "").strip()[:160]
    try:
        parsed = urlparse(receipt_url)
        port = parsed.port
    except ValueError:
        raise StoreError("发布回执 URL 无效") from None
    query_ids = parse_qs(parsed.query, keep_blank_values=True).get("id", [])
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.goofish.com"
        or port not in {None, 443}
        or parsed.path != "/item"
        or not re.fullmatch(r"\d{6,30}", item_id)
        or len(query_ids) != 1
        or query_ids[0] != item_id
    ):
        raise StoreError("发布回执必须是 item_id 一致的闲鱼 HTTPS 商品 URL")
    return receipt_url, item_id


def review_hash_from_row(row: sqlite3.Row) -> str:
    image_digests: list[dict[str, str]] = []
    for raw_path in json.loads(row["image_paths_json"]):
        path = Path(raw_path)
        if not path.is_file():
            raise StoreError("复核图片缺失，必须重新生成")
        image_digests.append(
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    material = {
        "description": row["description"],
        "images": image_digests,
        "quality_json": row["quality_json"],
        "source_type": row["source_type"],
        "external_id": row["external_id"],
        "title": row["title"],
        "facts_json": row["facts_json"],
        "price": row["price"],
        "original_price": row["original_price"],
        "delivery": row["delivery"],
        "shipping_fee": row["shipping_fee"],
        "location": row["location"],
        "source_url": row["source_url"],
        "notes": row["notes"],
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class StoreError(RuntimeError):
    pass


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(db_path.parent, 0o700)
        self._initialize()

    def _harden_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.db_path}{suffix}")
            if path.exists():
                os.chmod(path, 0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        self._harden_database_files()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_database_files()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    external_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    facts_json TEXT NOT NULL,
                    price TEXT NOT NULL,
                    original_price TEXT NOT NULL DEFAULT '',
                    delivery TEXT NOT NULL,
                    shipping_fee TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    rights_confirmed INTEGER NOT NULL CHECK(rights_confirmed = 1),
                    notes TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id),
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    content_mode TEXT NOT NULL DEFAULT '',
                    image_paths_json TEXT NOT NULL DEFAULT '[]',
                    quality_json TEXT NOT NULL DEFAULT '{}',
                    scheduled_for TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    review_hash TEXT NOT NULL DEFAULT '',
                    lease_hash TEXT NOT NULL DEFAULT '',
                    lease_until TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    receipt_url TEXT NOT NULL DEFAULT '',
                    receipt_item_id TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_queue
                ON jobs(status, scheduled_for, created_at);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
                """
            )
            db.execute("DROP INDEX IF EXISTS idx_sources_external")
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sources_external_lookup
                ON sources(source_type, external_id, created_at)
                WHERE external_id <> ''
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
            if "reviewed_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT ''")
            if "review_hash" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN review_hash TEXT NOT NULL DEFAULT ''")
            duplicate_receipt = db.execute(
                """
                SELECT receipt_item_id FROM jobs
                WHERE receipt_item_id <> ''
                GROUP BY receipt_item_id HAVING COUNT(*) > 1
                LIMIT 1
                """
            ).fetchone()
            if duplicate_receipt:
                raise StoreError(
                    f"检测到重复发布回执 item ID：{duplicate_receipt['receipt_item_id']}，"
                    "请先人工对账，系统已拒绝启动"
                )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_receipt_item_unique
                ON jobs(receipt_item_id) WHERE receipt_item_id <> ''
                """
            )

    def _event(self, db: sqlite3.Connection, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO events(job_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (job_id, event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_iso()),
        )

    def import_source(self, source: dict[str, Any], fingerprint: str) -> tuple[str, bool, str]:
        source_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        created = now_iso()
        idempotency_key = f"source:{fingerprint}:{job_id}"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = None
            if source["external_id"]:
                previous = db.execute(
                    """
                    SELECT j.id AS job_id, j.status, j.error_code, s.id AS source_id,
                        s.fingerprint
                    FROM sources s JOIN jobs j ON j.source_id = s.id
                    WHERE s.source_type = ? AND s.external_id = ?
                    ORDER BY j.rowid DESC LIMIT 1
                    """,
                    (source["source_type"], source["external_id"]),
                ).fetchone()
                if previous and previous["fingerprint"] == fingerprint:
                    return previous["job_id"], False, "duplicate"
                if previous and (
                    previous["status"] in {"RUNNING", "AWAITING_RECEIPT"}
                    or (previous["status"] == "BLOCKED" and previous["error_code"] == "RECEIPT_UNCERTAIN")
                ):
                    raise StoreError("同一商品存在执行中或回执不确定任务，完成对账前禁止更新来源")
            else:
                exact = db.execute(
                    """
                    SELECT j.id FROM jobs j JOIN sources s ON s.id = j.source_id
                    WHERE s.fingerprint = ? ORDER BY j.rowid DESC LIMIT 1
                    """,
                    (fingerprint,),
                ).fetchone()
                if exact:
                    return exact["id"], False, "duplicate"

            historical_source = db.execute(
                "SELECT id FROM sources WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if historical_source:
                source_id = historical_source["id"]
            else:
                db.execute(
                    """
                    INSERT INTO sources(
                        id, source_type, external_id, title, facts_json, price, original_price,
                        delivery, shipping_fee, location, source_url, rights_confirmed, notes,
                        fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        source_id,
                        source["source_type"],
                        source["external_id"],
                        source["title"],
                        json.dumps(source["facts"], ensure_ascii=False, sort_keys=True),
                        source["price"],
                        source["original_price"],
                        source["delivery"],
                        source["shipping_fee"],
                        source["location"],
                        source["source_url"],
                        source["notes"],
                        fingerprint,
                        created,
                    ),
                )
            db.execute(
                """
                INSERT INTO jobs(
                    id, source_id, status, idempotency_key, scheduled_for, created_at, updated_at
                ) VALUES (?, ?, 'INGESTED', ?, ?, ?, ?)
                """,
                (job_id, source_id, idempotency_key, created, created, created),
            )
            if previous and previous["status"] not in {"PUBLISHED", "SUPERSEDED"}:
                db.execute(
                    """
                    UPDATE jobs SET status = 'SUPERSEDED', approved_at = '', reviewed_at = '',
                        review_hash = '', lease_hash = '', lease_until = '',
                        error_code = 'SOURCE_UPDATED', error_message = '来源事实发生变化，旧任务已失效',
                        updated_at = ? WHERE id = ?
                    """,
                    (created, previous["job_id"]),
                )
                self._event(
                    db,
                    previous["job_id"],
                    "SUPERSEDED",
                    {"replacement_job_id": job_id, "replacement_fingerprint": fingerprint},
                )
            self._event(db, job_id, "IMPORTED", {"source_type": source["source_type"], "fingerprint": fingerprint})
            if previous:
                self._event(
                    db,
                    job_id,
                    "SOURCE_REVISION",
                    {"previous_job_id": previous["job_id"], "previous_status": previous["status"]},
                )
        return job_id, True, "revision" if previous else ""

    def source_for_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT s.* FROM sources s JOIN jobs j ON j.source_id = s.id WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        if not row:
            raise StoreError("任务不存在")
        source = dict(row)
        source["facts"] = json.loads(source.pop("facts_json"))
        source["rights_confirmed"] = bool(source["rights_confirmed"])
        return source

    def mark_generated(
        self,
        job_id: str,
        description: str,
        content_mode: str,
        image_paths: list[str],
        quality: dict[str, Any],
    ) -> None:
        if not quality.get("passed"):
            raise StoreError("质量检查未通过")
        with self.connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise StoreError("任务不存在")
            if row["status"] not in {"INGESTED", "FAILED"}:
                raise StoreError(f"状态 {row['status']} 不能重新生成")
            db.execute(
                """
                UPDATE jobs SET status = 'PENDING_APPROVAL', description = ?, content_mode = ?,
                    image_paths_json = ?, quality_json = ?, error_code = '', error_message = ?,
                    reviewed_at = '', review_hash = '', updated_at = ? WHERE id = ?
                """,
                (
                    description,
                    content_mode,
                    json.dumps(image_paths, ensure_ascii=False),
                    json.dumps(quality, ensure_ascii=False),
                    "",
                    now_iso(),
                    job_id,
                ),
            )
            self._event(db, job_id, "GENERATED", {"content_mode": content_mode, "image_count": len(image_paths), "quality": quality})

    def review(self, job_id: str, acknowledgement: str) -> dict[str, Any]:
        if acknowledgement != "确认已核对完整文案与商品事实":
            raise StoreError("确认文字必须是：确认已核对完整文案与商品事实")
        timestamp = now_iso()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT j.*, s.source_type, s.external_id, s.title, s.facts_json, s.price,
                    s.original_price, s.delivery, s.shipping_fee, s.location, s.source_url, s.notes
                FROM jobs j JOIN sources s ON s.id = j.source_id WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                raise StoreError("任务不存在")
            if row["status"] != "PENDING_APPROVAL":
                raise StoreError(f"状态 {row['status']} 不能标记复核")
            quality = json.loads(row["quality_json"])
            if not quality.get("passed"):
                raise StoreError("质量检查未通过")
            digest = review_hash_from_row(row)
            db.execute(
                "UPDATE jobs SET reviewed_at = ?, review_hash = ?, updated_at = ? WHERE id = ?",
                (timestamp, digest, timestamp, job_id),
            )
            self._event(db, job_id, "FULL_CONTENT_REVIEWED", {"review_hash": digest})
        return self.get_job(job_id)

    def approve(self, job_ids: list[str], acknowledgement: str) -> list[str]:
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            raise StoreError("没有选择任务")
        required = f"确认发布{len(unique_ids)}条"
        if acknowledgement != required:
            raise StoreError(f"确认文字必须是：{required}")
        timestamp = now_iso()
        approved: list[str] = []
        with self.connect() as db:
            for job_id in unique_ids:
                row = db.execute(
                    """
                    SELECT j.*, s.source_type, s.external_id, s.title, s.facts_json, s.price,
                        s.original_price, s.delivery, s.shipping_fee, s.location, s.source_url, s.notes
                    FROM jobs j JOIN sources s ON s.id = j.source_id WHERE j.id = ?
                    """,
                    (job_id,),
                ).fetchone()
                if not row:
                    raise StoreError(f"任务不存在：{job_id}")
                if row["status"] != "PENDING_APPROVAL":
                    raise StoreError(f"任务 {job_id} 当前状态不能审批：{row['status']}")
                quality = json.loads(row["quality_json"])
                if not quality.get("passed"):
                    raise StoreError(f"任务 {job_id} 的质量检查未通过")
                if not row["reviewed_at"] or row["review_hash"] != review_hash_from_row(row):
                    raise StoreError(f"任务 {job_id} 尚未完成完整内容复核")
                db.execute(
                    "UPDATE jobs SET status = 'APPROVED', approved_at = ?, updated_at = ? WHERE id = ?",
                    (timestamp, timestamp, job_id),
                )
                self._event(db, job_id, "APPROVED", {"scope_size": len(unique_ids)})
                approved.append(job_id)
        return approved

    def recover_expired(self, max_attempts: int) -> dict[str, int]:
        now = now_iso()
        recovered = 0
        failed = 0
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, attempt_count FROM jobs WHERE status = 'RUNNING' AND lease_until <> '' AND lease_until < ?",
                (now,),
            ).fetchall()
            for row in rows:
                if row["attempt_count"] >= max_attempts:
                    status = "FAILED"
                    failed += 1
                    code = "LEASE_EXHAUSTED"
                    message = "执行租约多次过期，已停止自动重试"
                else:
                    status = "APPROVED"
                    recovered += 1
                    code = "LEASE_RECOVERED"
                    message = "执行租约过期，任务已安全返回审批队列"
                db.execute(
                    """
                    UPDATE jobs SET status = ?, lease_hash = '', lease_until = '',
                        error_code = ?, error_message = ?, updated_at = ? WHERE id = ?
                    """,
                    (status, code, message, now, row["id"]),
                )
                self._event(db, row["id"], code, {"attempt_count": row["attempt_count"]})
        return {"recovered": recovered, "failed": failed}

    def queue_blocker(self) -> str:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT status, error_code FROM jobs
                WHERE status IN ('RUNNING', 'AWAITING_RECEIPT')
                   OR (status = 'BLOCKED' AND error_code = 'RECEIPT_UNCERTAIN')
                ORDER BY updated_at LIMIT 1
                """
            ).fetchone()
        if not row:
            return ""
        if row["status"] == "RUNNING":
            return "已有任务正在执行"
        if row["status"] == "AWAITING_RECEIPT":
            return "已有任务等待发布回执"
        return "存在提交结果不确定的任务，必须先人工对账"

    def lease_next(self, lease_seconds: int, max_attempts: int) -> dict[str, Any] | None:
        self.recover_expired(max_attempts)
        lease_token = secrets.token_urlsafe(32)
        now_dt = datetime.now(UTC).replace(microsecond=0)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                """
                SELECT 1 FROM jobs
                WHERE status IN ('RUNNING', 'AWAITING_RECEIPT')
                   OR (status = 'BLOCKED' AND error_code = 'RECEIPT_UNCERTAIN')
                LIMIT 1
                """
            ).fetchone()
            if active:
                return None
            row = db.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'APPROVED' AND scheduled_for <= ? AND attempt_count < ?
                ORDER BY scheduled_for, created_at LIMIT 1
                """,
                (now, max_attempts),
            ).fetchone()
            if not row:
                return None
            job_id = row["id"]
            changed = db.execute(
                """
                UPDATE jobs SET status = 'RUNNING', lease_hash = ?, lease_until = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND status = 'APPROVED'
                """,
                (_hash(lease_token), lease_until, now, job_id),
            ).rowcount
            if changed != 1:
                return None
            self._event(db, job_id, "LEASED", {"lease_until": lease_until})
        job = self.get_job(job_id, include_events=False)
        job["lease_token"] = lease_token
        return job

    def report(self, job_id: str, lease_token: str, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        stage = stage.lower()
        with self.connect() as db:
            row = db.execute("SELECT status, lease_hash FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise StoreError("任务不存在")
            if not secrets.compare_digest(row["lease_hash"], _hash(lease_token)):
                raise StoreError("执行租约无效")
            status = row["status"]
            if stage == "filled":
                if status != "RUNNING":
                    raise StoreError(f"状态 {status} 不能报告 filled")
                self._event(db, job_id, "FORM_FILLED", payload)
            elif stage == "submitting":
                if status != "RUNNING":
                    raise StoreError(f"状态 {status} 不能报告 submitting")
                db.execute(
                    "UPDATE jobs SET status = 'AWAITING_RECEIPT', updated_at = ? WHERE id = ?",
                    (now_iso(), job_id),
                )
                self._event(db, job_id, "SUBMITTING", payload)
            elif stage == "published":
                if status != "AWAITING_RECEIPT":
                    raise StoreError(f"状态 {status} 不能报告 published")
                receipt_url, item_id = validated_receipt(
                    str(payload.get("receipt_url") or ""),
                    str(payload.get("item_id") or ""),
                )
                try:
                    db.execute(
                        """
                        UPDATE jobs SET status = 'PUBLISHED', receipt_url = ?, receipt_item_id = ?,
                            lease_hash = '', lease_until = '', error_code = '', error_message = '',
                            updated_at = ? WHERE id = ?
                        """,
                        (receipt_url, item_id, now_iso(), job_id),
                    )
                except sqlite3.IntegrityError:
                    raise StoreError("该发布回执 item ID 已归属于其他任务，必须人工对账") from None
                self._event(db, job_id, "PUBLISHED", {"receipt_url": receipt_url, "item_id": item_id})
            elif stage in {"blocked", "failed"}:
                target = "BLOCKED" if stage == "blocked" else "FAILED"
                code = str(payload.get("code") or stage.upper())[:100]
                message = str(payload.get("message") or "")[:1000]
                db.execute(
                    """
                    UPDATE jobs SET status = ?, lease_hash = '', lease_until = '',
                        error_code = ?, error_message = ?, updated_at = ? WHERE id = ?
                    """,
                    (target, code, message, now_iso(), job_id),
                )
                self._event(db, job_id, target, {"code": code, "message": message})
            else:
                raise StoreError("未知执行报告阶段")
        return self.get_job(job_id)

    def retry(self, job_id: str, acknowledgement: str) -> None:
        if acknowledgement != "确认重新排队":
            raise StoreError("确认文字必须是：确认重新排队")
        with self.connect() as db:
            row = db.execute("SELECT status, error_code FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise StoreError("任务不存在")
            if row["status"] not in {"FAILED", "BLOCKED"}:
                raise StoreError(f"状态 {row['status']} 不能重新排队")
            if row["error_code"] == "RECEIPT_UNCERTAIN":
                raise StoreError("提交结果不确定，必须先对账，禁止直接重新排队")
            db.execute(
                """
                UPDATE jobs SET status = 'PENDING_APPROVAL', approved_at = '', lease_hash = '',
                    lease_until = '', attempt_count = 0, error_code = '', error_message = '',
                    updated_at = ? WHERE id = ?
                """,
                (now_iso(), job_id),
            )
            self._event(db, job_id, "REQUEUED_FOR_REVIEW", {})

    def reconcile(
        self,
        job_id: str,
        decision: str,
        acknowledgement: str,
        receipt_url: str = "",
        item_id: str = "",
    ) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT status, error_code FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                raise StoreError("任务不存在")
            if row["status"] not in {"AWAITING_RECEIPT", "BLOCKED"}:
                raise StoreError(f"状态 {row['status']} 不需要提交结果对账")
            if row["status"] == "BLOCKED" and row["error_code"] != "RECEIPT_UNCERTAIN":
                raise StoreError("该阻塞不是回执不确定，不能使用对账入口")
            timestamp = now_iso()
            if decision == "found_published":
                if acknowledgement != "确认回执归属该任务":
                    raise StoreError("确认文字必须是：确认回执归属该任务")
                valid_url, valid_id = validated_receipt(receipt_url, item_id)
                try:
                    db.execute(
                        """
                        UPDATE jobs SET status = 'PUBLISHED', receipt_url = ?, receipt_item_id = ?,
                            lease_hash = '', lease_until = '', error_code = '', error_message = '',
                            updated_at = ? WHERE id = ?
                        """,
                        (valid_url, valid_id, timestamp, job_id),
                    )
                except sqlite3.IntegrityError:
                    raise StoreError("该发布回执 item ID 已归属于其他任务，必须人工对账") from None
                self._event(db, job_id, "RECONCILED_PUBLISHED", {"receipt_url": valid_url, "item_id": valid_id})
            elif decision == "verified_not_published":
                if acknowledgement != "确认未发布并重新排队":
                    raise StoreError("确认文字必须是：确认未发布并重新排队")
                db.execute(
                    """
                    UPDATE jobs SET status = 'PENDING_APPROVAL', approved_at = '',
                        lease_hash = '', lease_until = '', attempt_count = 0,
                        error_code = '', error_message = '', updated_at = ? WHERE id = ?
                    """,
                    (timestamp, job_id),
                )
                self._event(db, job_id, "RECONCILED_NOT_PUBLISHED", {"next": "PENDING_APPROVAL"})
            else:
                raise StoreError("未知对账决定")
        return self.get_job(job_id)

    def get_job(self, job_id: str, include_events: bool = True) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT j.*, s.source_type, s.external_id, s.title, s.facts_json, s.price,
                    s.original_price, s.delivery, s.shipping_fee, s.location, s.source_url,
                    s.rights_confirmed, s.notes
                FROM jobs j JOIN sources s ON s.id = j.source_id WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                raise StoreError("任务不存在")
            job = self._decode_job(row)
            if include_events:
                events = db.execute(
                    "SELECT id, event_type, payload_json, created_at FROM events WHERE job_id = ? ORDER BY id",
                    (job_id,),
                ).fetchall()
                job["events"] = [
                    {
                        "id": event["id"],
                        "event_type": event["event_type"],
                        "payload": json.loads(event["payload_json"]),
                        "created_at": event["created_at"],
                    }
                    for event in events
                ]
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT j.*, s.source_type, s.external_id, s.title, s.facts_json, s.price,
                    s.original_price, s.delivery, s.shipping_fee, s.location, s.source_url,
                    s.rights_confirmed, s.notes
                FROM jobs j JOIN sources s ON s.id = j.source_id
                ORDER BY j.created_at DESC
                """
            ).fetchall()
        return [self._decode_job(row) for row in rows]

    @staticmethod
    def _decode_job(row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        job["facts"] = json.loads(job.pop("facts_json"))
        job["image_paths"] = json.loads(job.pop("image_paths_json"))
        job["quality"] = json.loads(job.pop("quality_json"))
        job["rights_confirmed"] = bool(job["rights_confirmed"])
        job.pop("lease_hash", None)
        return job
