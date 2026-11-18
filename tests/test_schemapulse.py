"""Unit test suite for SchemaPulse schema inference, codegen, and data drift detection."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemapulse.cli import main
from schemapulse.differ import diff_schemas, diff_sources
from schemapulse.inferrer import (
    detect_string_format,
    infer_schema,
    to_json_schema,
    to_typed_dict_code,
)
from schemapulse.models import DriftSeverity


class TestSchemaPulseInferenceAndDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_jsonl(self, name: str, records: list[dict]) -> Path:
        path = self.root / name
        content = "\n".join(json.dumps(r) for r in records) + "\n"
        path.write_text(content, encoding="utf-8")
        return path

    def test_detect_string_formats(self) -> None:
        self.assertEqual(
            detect_string_format("2026-11-18T04:27:07Z"), "iso-datetime"
        )
        self.assertEqual(
            detect_string_format("2026-11-18 14:30:00+09:00"), "iso-datetime"
        )
        self.assertEqual(detect_string_format("2026-11-18"), "iso-date")
        self.assertEqual(
            detect_string_format("550e8400-e29b-41d4-a716-446655440000"),
            "uuid",
        )
        self.assertEqual(
            detect_string_format("spectacle2002@gmail.com"), "email"
        )
        self.assertEqual(
            detect_string_format("https://github.com/Dharmogata/schemapulse"),
            "uri",
        )
        self.assertEqual(detect_string_format("paid"), "plain")

    def test_recursive_jsonl_profiling_and_codegen(self) -> None:
        records = [
            {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2026-11-18T01:00:00Z",
                "status": "paid",
                "user": {
                    "email": "alice@example.com",
                    "address": {"zip": "94107", "country": "US"},
                },
                "items": [
                    {"sku": "A1", "price": 19.5, "qty": 1},
                    {"sku": "B2", "price": 42.0, "qty": 3},
                ],
                "coupon": None,
            },
            {
                "event_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "created_at": "2026-11-18T02:00:00Z",
                "status": "shipped",
                "user": {
                    "email": "bob@example.com",
                    "address": {"zip": "10001", "country": "US"},
                },
                "items": [
                    {"sku": "C3", "price": 9.99, "qty": 2},
                ],
            },
        ]
        jsonl_path = self._write_jsonl("orders.jsonl", records)
        snap = infer_schema(jsonl_path)

        self.assertEqual(snap.total_records, 2)
        self.assertIn("user.address.zip", snap.fields)
        self.assertIn("items[].price", snap.fields)
        self.assertEqual(
            snap.fields["event_id"].dominant_string_format, "uuid"
        )
        self.assertEqual(
            snap.fields["created_at"].dominant_string_format, "iso-datetime"
        )
        self.assertEqual(
            snap.fields["user.email"].dominant_string_format, "email"
        )
        self.assertEqual(snap.fields["items[].price"].min_number, 9.99)
        self.assertEqual(snap.fields["items[].price"].max_number, 42.0)
        self.assertEqual(snap.fields["coupon"].required_ratio, 0.5)
        self.assertTrue(snap.fields["coupon"].nullable)

        # JSON Schema Draft 2020-12 export
        schema = to_json_schema(snap)
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(
            schema["properties"]["event_id"]["format"], "uuid"
        )
        self.assertEqual(
            schema["properties"]["status"]["enum"], ["paid", "shipped"]
        )
        self.assertIn("event_id", schema["required"])
        self.assertNotIn("coupon", schema["required"])

        # Python TypedDict codegen
        td_code = to_typed_dict_code(snap)
        self.assertIn("class Record(TypedDict):", td_code)
        self.assertIn("class UserAddress(TypedDict):", td_code)
        self.assertIn("class ItemsItem(TypedDict):", td_code)
        self.assertIn("Literal['paid', 'shipped']", td_code)
        self.assertIn("coupon: NotRequired[None]", td_code)

    def test_sp001_to_sp005_drift_rules(self) -> None:
        baseline_records = [
            {
                "order_id": 1001,
                "customer_id": "c_1",
                "status": "pending",
                "created_at": "2026-11-18T00:00:00Z",
            },
            {
                "order_id": 1002,
                "customer_id": "c_2",
                "status": "paid",
                "created_at": "2026-11-18T01:00:00Z",
            },
        ]
        candidate_records = [
            {
                # SP001: integer -> string mutation
                "order_id": "ORD-1003",
                # SP002: customer_id was required & non-null, now null
                "customer_id": None,
                # SP003: status added unseen enum value 'chargeback_pending'
                "status": "chargeback_pending",
                # SP004: created_at degraded from iso-datetime to plain string
                "created_at": "yesterday afternoon",
                # SP005: undocumented new field
                "debug_trace": "trace-xyz",
            }
        ]
        base_snap = infer_schema(baseline_records, source_name="baseline.jsonl")
        cand_snap = infer_schema(candidate_records, source_name="candidate.jsonl")

        report = diff_schemas(base_snap, cand_snap)
        rule_ids = {f.rule_id for f in report.findings}
        self.assertEqual(rule_ids, {"SP001", "SP002", "SP003", "SP004", "SP005"})
        self.assertEqual(report.critical_count, 1)
        self.assertEqual(report.high_count, 1)

        # Filtering by min_severity=HIGH should keep only SP001 and SP002
        high_report = diff_schemas(
            base_snap, cand_snap, min_severity=DriftSeverity.HIGH
        )
        self.assertEqual(
            {f.rule_id for f in high_report.findings}, {"SP001", "SP002"}
        )

    def test_cli_infer_diff_and_rules(self) -> None:
        base_file = self._write_jsonl(
            "base.jsonl",
            [
                {"id": 1, "state": "open"},
                {"id": 2, "state": "closed"},
            ],
        )
        cand_file = self._write_jsonl(
            "cand.jsonl",
            [
                {"id": "two", "state": "archived", "extra": True},
            ],
        )

        # 1. CLI infer --format jsonschema
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            rc = main(["infer", str(base_file), "--format", "jsonschema"])
            self.assertEqual(rc, 0)
            schema_doc = json.loads(mock_out.getvalue())
            self.assertIn("properties", schema_doc)

        # 2. CLI diff --format json --fail-on-drift
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            rc = main(
                [
                    "diff",
                    str(base_file),
                    str(cand_file),
                    "--format",
                    "json",
                    "--fail-on-drift",
                ]
            )
            self.assertEqual(rc, 1)
            drift_payload = json.loads(mock_out.getvalue())
            self.assertGreaterEqual(drift_payload["total_findings"], 3)

        # 3. CLI rules
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            rc = main(["rules"])
            self.assertEqual(rc, 0)
            self.assertIn("SP001", mock_out.getvalue())
            self.assertIn("SP005", mock_out.getvalue())

        # 4. CLI infer --format typeddict & markdown, diff --format markdown
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            rc = main(["infer", str(base_file), "--format", "typeddict"])
            self.assertEqual(rc, 0)
            self.assertIn("class Record(TypedDict):", mock_out.getvalue())

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            rc = main(
                ["diff", str(base_file), str(cand_file), "--format", "markdown"]
            )
            self.assertEqual(rc, 0)
            self.assertIn("SchemaPulse Drift Report", mock_out.getvalue())


if __name__ == "__main__":
    unittest.main()
