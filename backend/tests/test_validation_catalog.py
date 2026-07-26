from __future__ import annotations

import unittest

from app.validation.catalog import validation_catalog_payload


class ValidationCatalogTest(unittest.TestCase):
    def test_catalog_owns_filter_order_and_default_visibility(self) -> None:
        catalog = validation_catalog_payload()

        self.assertEqual(
            [item["label"] for item in catalog],
            [
                "합계 검수",
                "비율 검수",
                "오탈자 검수",
                "번역 검수",
                "메타정보 검수",
                "이상치 검수",
                "파란색 표기 확인",
            ],
        )
        self.assertEqual([item["order"] for item in catalog], list(range(len(catalog))))
        self.assertFalse(next(item for item in catalog if item["key"] == "outlier")["default_visible"])
        self.assertTrue(
            all(
                item["default_visible"]
                for item in catalog
                if item["key"] != "outlier"
            )
        )


if __name__ == "__main__":
    unittest.main()
