"""Command-line interface for SchemaPulse schema inference, codegen, and drift detection."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Optional

from schemapulse import __version__
from schemapulse.differ import diff_sources, get_default_rules
from schemapulse.formatters import (
    format_drift_report,
    format_rules_catalog,
    format_schema_snapshot,
)
from schemapulse.inferrer import infer_schema
from schemapulse.models import DriftSeverity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schemapulse",
        description=(
            "Streaming JSONL schema lattice inferrer, JSON Schema & TypedDict codegen, "
            "and silent data drift detector."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"schemapulse {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    infer_p = subparsers.add_parser(
        "infer",
        help="Infer a schema lattice, JSON Schema, or TypedDict code from JSONL/JSON records.",
    )
    infer_p.add_argument(
        "path",
        help="Target JSONL/JSON file or directory path.",
    )
    infer_p.add_argument(
        "--format",
        choices=["text", "json", "markdown", "jsonschema", "typeddict"],
        default="text",
        help="Output format (default: text).",
    )

    diff_p = subparsers.add_parser(
        "diff",
        help="Compare baseline and candidate JSONL/JSON streams for schema drift.",
    )
    diff_p.add_argument(
        "baseline_path",
        help="Baseline JSONL/JSON file or directory path.",
    )
    diff_p.add_argument(
        "candidate_path",
        help="Candidate JSONL/JSON file or directory path.",
    )
    diff_p.add_argument(
        "--min-severity",
        choices=["low", "medium", "high", "critical"],
        default="low",
        help="Minimum drift severity threshold (default: low).",
    )
    diff_p.add_argument(
        "--select",
        default=None,
        help="Comma-separated list of rule IDs to enable (e.g., SP001,SP002).",
    )
    diff_p.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output report format (default: text).",
    )
    diff_p.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit with status code 1 if any drift findings match the severity threshold.",
    )

    rules_p = subparsers.add_parser(
        "rules",
        help="List all built-in schema drift detection rules (SP001-SP005).",
    )
    rules_p.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "rules":
        print(format_rules_catalog(get_default_rules(), output_format=args.format))
        return 0

    if args.command == "infer":
        target = Path(args.path)
        if not target.exists():
            print(f"Error: Path not found: {target}", file=sys.stderr)
            return 2

        snapshot = infer_schema(target)
        print(format_schema_snapshot(snapshot, output_format=args.format))
        return 0

    if args.command == "diff":
        base_target = Path(args.baseline_path)
        cand_target = Path(args.candidate_path)
        if not base_target.exists():
            print(f"Error: Baseline path not found: {base_target}", file=sys.stderr)
            return 2
        if not cand_target.exists():
            print(f"Error: Candidate path not found: {cand_target}", file=sys.stderr)
            return 2

        selected = (
            {s.strip() for s in args.select.split(",") if s.strip()}
            if args.select
            else None
        )
        report = diff_sources(
            base_target,
            cand_target,
            min_severity=DriftSeverity(args.min_severity),
            select_rules=selected,
        )
        print(format_drift_report(report, output_format=args.format))
        if args.fail_on_drift and report.findings:
            return 1
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
