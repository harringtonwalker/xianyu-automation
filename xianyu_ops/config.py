from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "brand_name": "你的品牌",
    "watermark_text": "你的品牌 · 原创服务",
    "publisher_enabled": False,
    "max_publish_attempts": 3,
    "lease_seconds": 180,
    "default_delivery": "无需邮寄",
    "default_location_mode": "KEEP_ACCOUNT_DEFAULT",
}
PRIVATE_KEYS = {"extension_token", "approval_secret"}


def ensure_config(data_dir: Path) -> tuple[dict[str, Any], str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    config_path = data_dir / "config.json"
    if config_path.exists():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        payload = {}
    changed = False
    if "approval_secret" in payload:
        payload.pop("approval_secret")
        changed = True
    for key, value in DEFAULTS.items():
        if key not in payload:
            payload[key] = value
            changed = True
    if "extension_token" not in payload:
        payload["extension_token"] = secrets.token_urlsafe(32)
        changed = True
    if changed:
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    os.chmod(config_path, 0o600)
    public = {key: value for key, value in payload.items() if key not in PRIVATE_KEYS}
    return public, payload["extension_token"]


def load_private_config(data_dir: Path) -> dict[str, Any]:
    ensure_config(data_dir)
    return json.loads((data_dir / "config.json").read_text(encoding="utf-8"))


def update_public_config(data_dir: Path, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "brand_name",
        "watermark_text",
        "max_publish_attempts",
        "lease_seconds",
        "default_delivery",
        "default_location_mode",
    }
    private = load_private_config(data_dir)
    for key, value in changes.items():
        if key in allowed:
            if key in {"brand_name", "watermark_text"}:
                value = str(value).strip()
                if not value:
                    raise ValueError(f"{key} 不能为空")
                if len(value) > (40 if key == "brand_name" else 80):
                    raise ValueError(f"{key} 过长")
            if key == "max_publish_attempts":
                value = int(value)
                if value < 1 or value > 5:
                    raise ValueError("max_publish_attempts 必须为 1 到 5")
            if key == "lease_seconds":
                value = int(value)
                if value < 60 or value > 900:
                    raise ValueError("lease_seconds 必须为 60 到 900")
            private[key] = value
    (data_dir / "config.json").write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(data_dir / "config.json", 0o600)
    return {key: value for key, value in private.items() if key not in PRIVATE_KEYS}


def set_publisher_enabled(data_dir: Path, enabled: bool, acknowledgement: str) -> bool:
    required = "启用自动发布" if enabled else "关闭自动发布"
    if acknowledgement != required:
        raise ValueError(f"确认文字必须是：{required}")
    private = load_private_config(data_dir)
    private["publisher_enabled"] = enabled
    (data_dir / "config.json").write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(data_dir / "config.json", 0o600)
    return enabled


def force_disable_publisher(data_dir: Path) -> None:
    private = load_private_config(data_dir)
    if private.get("publisher_enabled") is False:
        return
    private["publisher_enabled"] = False
    (data_dir / "config.json").write_text(
        json.dumps(private, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(data_dir / "config.json", 0o600)
