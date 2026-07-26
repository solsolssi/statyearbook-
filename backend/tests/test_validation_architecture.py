from __future__ import annotations

from pathlib import Path
import re
import unittest

from app.validation.profile_rules import ProfileSpecRule
from app.validation.catalog import (
    LLM_PROFILE_RULE_TYPES,
    PROFILE_SPEC_EXECUTORS,
    SUPPORTED_PROFILE_SPEC_TYPES,
    check_group_for_rule_type,
)


class ValidationArchitectureTests(unittest.TestCase):
    def test_every_profile_executor_points_to_an_existing_method(self) -> None:
        rule = ProfileSpecRule({})

        for rule_type, method_name in PROFILE_SPEC_EXECUTORS.items():
            with self.subTest(rule_type=rule_type):
                self.assertTrue(callable(getattr(rule, method_name, None)))

    def test_llm_profile_types_are_part_of_the_persisted_spec_contract(self) -> None:
        self.assertTrue(LLM_PROFILE_RULE_TYPES <= SUPPORTED_PROFILE_SPEC_TYPES)

    def test_rule_groups_are_derived_from_the_shared_catalog(self) -> None:
        self.assertEqual(check_group_for_rule_type("row_sum"), "sum")
        self.assertEqual(check_group_for_rule_type("row_ratio"), "ratio")
        self.assertEqual(check_group_for_rule_type("row_growth_rate"), "growth_rate")

    def test_sqlite_driver_is_confined_to_the_database_adapter(self) -> None:
        app_root = Path(__file__).parents[1] / "app"
        offenders: list[str] = []
        for path in app_root.rglob("*.py"):
            if path == app_root / "db" / "connection.py":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"\b(?:import|from)\s+sqlite3\b|\bsqlite3\.(?:Connection|Row)\b", text):
                offenders.append(str(path.relative_to(app_root)))
        self.assertEqual(offenders, [])

    def test_runtime_validation_modules_use_the_canonical_result_repository(self) -> None:
        validation_root = Path(__file__).parents[1] / "app" / "validation"
        offenders: list[str] = []
        write_pattern = re.compile(
            r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+validation_checks",
            re.IGNORECASE,
        )
        for path in validation_root.glob("*.py"):
            if path.name == "result_repository.py":
                continue
            if write_pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
