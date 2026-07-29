from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any


ALLOWED_DELIVERY = {"包邮", "按距离计费", "一口价", "无需邮寄"}
FORBIDDEN_CLAIMS = (
    "全网最低",
    "100%保证",
    "百分百保证",
    "保证通过",
    "绝对有效",
    "官方授权",
    "无任何风险",
)
RISK_SIGNALS = (
    "验证码",
    "滑块",
    "安全验证",
    "异常操作",
    "访问受限",
    "账号存在风险",
    "操作过于频繁",
)


class PolicyError(ValueError):
    pass


def _clean_text(value: Any, limit: int = 5000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def price_text(value: Any, field: str) -> str:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        amount = amount.quantize(Decimal("0.01"))
        if amount <= 0 or amount > Decimal("9999999"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise PolicyError(f"{field} 不是有效价格") from None
    return format(amount, "f")


def normalize_source(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("rights_confirmed") is not True:
        raise PolicyError("仅可导入自有或已明确授权的商品，rights_confirmed 必须为 true")
    title = _clean_text(raw.get("title"), 120)
    if len(title) < 2:
        raise PolicyError("title 至少需要 2 个字符")
    source_type = _clean_text(raw.get("source_type") or "local", 32).lower()
    if source_type not in {"local", "taobao-own", "xianyu-own", "authorized-url"}:
        raise PolicyError("source_type 不在授权来源范围内")
    external_id = _clean_text(raw.get("external_id") or raw.get("sku") or "", 160)
    if not external_id:
        raise PolicyError("external_id 或 sku 必须提供稳定商品标识，用于修订与防重复")
    source_url = _clean_text(raw.get("source_url"), 1000)
    if source_type == "authorized-url" and not source_url.startswith(("https://", "http://")):
        raise PolicyError("authorized-url 必须提供有效 source_url")
    facts = raw.get("facts") or {}
    if isinstance(facts, str):
        facts = {"详情": _clean_text(facts, 1600)}
    elif isinstance(facts, list):
        facts = {f"要点{i + 1}": _clean_text(item, 300) for i, item in enumerate(facts[:12])}
    elif isinstance(facts, dict):
        facts = {
            _clean_text(key, 60): _clean_text(value, 500)
            for key, value in list(facts.items())[:20]
            if _clean_text(key, 60) and _clean_text(value, 500)
        }
    else:
        raise PolicyError("facts 必须是对象、数组或文本")
    if not facts:
        raise PolicyError("facts 至少需要一个可核验事实")
    delivery = _clean_text(raw.get("delivery"), 20)
    if delivery not in ALLOWED_DELIVERY:
        raise PolicyError(f"delivery 必须是：{', '.join(sorted(ALLOWED_DELIVERY))}")
    price = price_text(raw.get("price"), "price")
    original_raw = raw.get("original_price")
    original_price = price_text(original_raw, "original_price") if original_raw not in (None, "") else ""
    if original_price and Decimal(original_price) < Decimal(price):
        raise PolicyError("original_price 不能低于 price")
    shipping_raw = raw.get("shipping_fee")
    if delivery == "一口价":
        shipping_fee = price_text(shipping_raw, "shipping_fee")
    else:
        if shipping_raw not in (None, ""):
            raise PolicyError("只有 delivery=一口价 时才允许填写 shipping_fee")
        shipping_fee = ""
    location = _clean_text(raw.get("location"), 80)
    if location:
        raise PolicyError("当前发布适配器保持账号默认所在地，location 必须留空")
    return {
        "source_type": source_type,
        "external_id": external_id,
        "title": title,
        "facts": facts,
        "price": price,
        "original_price": original_price,
        "delivery": delivery,
        "shipping_fee": shipping_fee,
        "location": "",
        "source_url": source_url,
        "rights_confirmed": True,
        "notes": _clean_text(raw.get("notes"), 1000),
    }


def quality_check(source: dict[str, Any], description: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not source.get("rights_confirmed"):
        errors.append("来源权属未确认")
    if not 20 <= len(description) <= 1500:
        errors.append("描述必须为 20 到 1500 个字符")
    for claim in FORBIDDEN_CLAIMS:
        if claim in description:
            errors.append(f"包含未经证据支持的高风险表述：{claim}")
    if not source.get("source_url") and source.get("source_type") != "local":
        warnings.append("非本地来源未记录 source_url")
    if not source.get("original_price"):
        warnings.append("未填写原价")
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def canonical_fingerprint(source: dict[str, Any]) -> str:
    import hashlib

    # Fingerprint every normalized field that can affect provenance, generated
    # content, review, transaction terms, or publication behavior. Omitting even
    # an "internal" note is unsafe because notes are included in the listing copy.
    stable = {key: source[key] for key in sorted(source)}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
