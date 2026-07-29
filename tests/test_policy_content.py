from __future__ import annotations

import unittest

from xianyu_ops.content import deterministic_description
from xianyu_ops.policy import PolicyError, canonical_fingerprint, normalize_source, quality_check


def valid_raw() -> dict:
    return {
        "source_type": "local",
        "external_id": "SKU-001",
        "title": "门店小程序定制服务",
        "facts": {"交付内容": "小程序源码与管理后台", "适用范围": "本地门店"},
        "price": "1999",
        "original_price": "2999",
        "delivery": "无需邮寄",
        "rights_confirmed": True,
    }


class PolicyContentTests(unittest.TestCase):
    def test_normalize_and_description_stay_within_contract(self) -> None:
        source = normalize_source(valid_raw())
        description = deterministic_description(source, "示例品牌")
        quality = quality_check(source, description)
        self.assertTrue(quality["passed"])
        self.assertIn("小程序源码与管理后台", description)
        self.assertIn("示例品牌", description)
        self.assertLessEqual(len(description), 1500)

    def test_rights_confirmation_is_mandatory(self) -> None:
        raw = valid_raw()
        raw["rights_confirmed"] = False
        with self.assertRaisesRegex(PolicyError, "rights_confirmed"):
            normalize_source(raw)

    def test_delivery_must_be_explicit(self) -> None:
        raw = valid_raw()
        raw["delivery"] = ""
        with self.assertRaisesRegex(PolicyError, "delivery"):
            normalize_source(raw)

    def test_external_source_requires_url(self) -> None:
        raw = valid_raw()
        raw["source_type"] = "authorized-url"
        with self.assertRaisesRegex(PolicyError, "source_url"):
            normalize_source(raw)

    def test_stable_external_id_is_mandatory(self) -> None:
        raw = valid_raw()
        raw["external_id"] = ""
        with self.assertRaisesRegex(PolicyError, "external_id"):
            normalize_source(raw)

    def test_original_price_cannot_be_lower(self) -> None:
        raw = valid_raw()
        raw["original_price"] = "99"
        with self.assertRaisesRegex(PolicyError, "不能低于"):
            normalize_source(raw)

    def test_non_finite_price_is_rejected(self) -> None:
        raw = valid_raw()
        raw["price"] = "NaN"
        with self.assertRaisesRegex(PolicyError, "有效价格"):
            normalize_source(raw)

    def test_custom_location_is_rejected_until_semantic_adapter_exists(self) -> None:
        raw = valid_raw()
        raw["location"] = "北京"
        with self.assertRaisesRegex(PolicyError, "location 必须留空"):
            normalize_source(raw)

    def test_fingerprint_changes_for_every_material_source_change(self) -> None:
        first = normalize_source(valid_raw())
        changes = [
            {"notes": "需要展示给买家的补充说明"},
            {"original_price": "3999"},
            {"delivery": "包邮"},
        ]
        for change in changes:
            with self.subTest(change=change):
                changed = normalize_source({**valid_raw(), **change})
                self.assertNotEqual(canonical_fingerprint(first), canonical_fingerprint(changed))

    def test_flat_shipping_requires_a_valid_fee(self) -> None:
        with self.assertRaisesRegex(PolicyError, "shipping_fee"):
            normalize_source({**valid_raw(), "delivery": "一口价"})
        with self.assertRaisesRegex(PolicyError, "shipping_fee"):
            normalize_source({**valid_raw(), "delivery": "一口价", "shipping_fee": "免费"})
        source = normalize_source({**valid_raw(), "delivery": "一口价", "shipping_fee": "12.5"})
        self.assertEqual(source["shipping_fee"], "12.50")

    def test_non_flat_delivery_rejects_stale_shipping_fee(self) -> None:
        with self.assertRaisesRegex(PolicyError, "一口价"):
            normalize_source({**valid_raw(), "shipping_fee": "12"})

    def test_forbidden_claim_is_rejected(self) -> None:
        source = normalize_source(valid_raw())
        quality = quality_check(source, "这是一个全网最低的商品描述，包含足够多的描述字符用于测试。")
        self.assertFalse(quality["passed"])
        self.assertTrue(any("全网最低" in item for item in quality["errors"]))


if __name__ == "__main__":
    unittest.main()
