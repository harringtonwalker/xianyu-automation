from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def deterministic_description(source: dict[str, Any], brand_name: str) -> str:
    facts = source["facts"]
    fact_lines = [f"• {key}：{value}" for key, value in facts.items()]
    delivery_notes = {
        "无需邮寄": "线上沟通需求与交付，不涉及实物邮寄。",
        "包邮": "标价已包含普通运费，偏远地区请先沟通。",
        "按距离计费": "运费以平台按距离计算结果为准。",
        "一口价": "邮费按页面所示一口价计算。",
    }
    blocks = [
        source["title"],
        "",
        "【商品/服务详情】",
        *fact_lines,
        "",
        "【交易说明】",
        delivery_notes[source["delivery"]],
        "具体范围、交付时间和适配条件以下单前双方确认内容为准。",
        "页面内容根据已授权的商品资料生成，如有疑问请先咨询再下单。",
    ]
    if source.get("notes"):
        blocks.extend(["", "【补充说明】", source["notes"]])
    blocks.extend(["", f"品牌标识：{brand_name}"])
    return "\n".join(blocks)[:1500]


def provider_description(source: dict[str, Any], brand_name: str) -> str | None:
    endpoint = os.environ.get("XIANYU_AI_ENDPOINT", "").strip()
    api_key = os.environ.get("XIANYU_AI_API_KEY", "").strip()
    model = os.environ.get("XIANYU_AI_MODEL", "").strip()
    allow = os.environ.get("XIANYU_ALLOW_PAID_PROVIDER") == "1"
    if not (endpoint and api_key and model and allow):
        return None
    prompt = {
        "task": "基于输入事实撰写闲鱼中文商品描述，不添加输入中没有的承诺、资质、效果或数据。",
        "requirements": [
            "20到1500字",
            "首行写商品名",
            "结构清晰，强调真实交付范围",
            "禁止全网最低、百分百、保证通过、官方授权等无证据表述",
            f"末尾保留品牌标识：{brand_name}",
        ],
        "source": source,
    }
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是严格依赖事实的二手交易商品编辑。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read())
    return str(payload["choices"][0]["message"]["content"]).strip()[:1500]


def generate_description(source: dict[str, Any], brand_name: str) -> tuple[str, str]:
    provider_result = provider_description(source, brand_name)
    if provider_result:
        return provider_result, "provider"
    return deterministic_description(source, brand_name), "deterministic"
