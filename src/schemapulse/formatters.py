"""Output formatters for SchemaPulse snapshots, codegen, drift reports, and rules."""

from __future__ import annotations

import json
from typing import List, Sequence

from schemapulse.inferrer import to_json_schema, to_typed_dict_code
from schemapulse.models import DriftReport, DriftRuleSpec, FieldProfile, SchemaSnapshot


def _field_constraint_summary(fp: FieldProfile) -> str:
    parts: List[str] = []
    dom_fmt = fp.dominant_string_format
    if dom_fmt:
        parts.append(f"format={dom_fmt}")
    if fp.min_number is not None and fp.max_number is not None:
        parts.append(f"range=[{fp.min_number}, {fp.max_number}]")
    if (
        not dom_fmt
        and "string" in fp.non_null_types
        and not fp.distinct_overflow
        and 1 <= len(fp.distinct_values) <= 10
    ):
        parts.append(f"enum={fp.distinct_values}")
    return ", ".join(parts) if parts else "-"


def format_schema_snapshot(
    snapshot: SchemaSnapshot,
    output_format: str = "text",
) -> str:
    """Format a SchemaSnapshot as text, json, markdown, jsonschema, or typeddict."""
    if output_format == "json":
        return json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)

    if output_format == "jsonschema":
        return json.dumps(to_json_schema(snapshot), indent=2, ensure_ascii=False)

    if output_format == "typeddict":
        return to_typed_dict_code(snapshot).rstrip()

    if output_format == "markdown":
        lines: List[str] = [
            f"# SchemaPulse Inferred Profile (`{snapshot.source_name}`)",
            "",
            f"- **Total Records Profiled:** {snapshot.total_records}",
            f"- **Total Field Paths:** {len(snapshot.fields)}",
            "",
            "| Field Path | Types | Required | Nullable | Constraints / Domain |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for path, fp in sorted(snapshot.fields.items()):
            types_str = " \\| ".join(sorted(fp.types_counts.keys()))
            req_pct = f"{round(fp.required_ratio * 100, 1)}%"
            lines.append(
                f"| `{path}` | `{types_str}` | {req_pct} | `{fp.nullable}` | {_field_constraint_summary(fp)} |"
            )
        return "\n".join(lines)

    lines = [
        f"SchemaPulse Inferred Lattice ({snapshot.source_name} · {snapshot.total_records} record(s))",
        "─" * 86,
        f"  {'FIELD PATH':<26} {'TYPES':<18} {'REQ%':<8} {'NULLABLE':<10} CONSTRAINTS",
        "─" * 86,
    ]
    for path, fp in sorted(snapshot.fields.items()):
        types_str = "|".join(sorted(fp.types_counts.keys()))
        req_pct = f"{round(fp.required_ratio * 100, 1)}%"
        nullable_str = "yes" if fp.nullable else "no"
        constraints = _field_constraint_summary(fp)
        lines.append(
            f"  {path:<26} {types_str:<18} {req_pct:<8} {nullable_str:<10} {constraints}"
        )
    lines.append("─" * 86)
    lines.append(f"Total fields profiled: {len(snapshot.fields)}")
    return "\n".join(lines)


def format_drift_report(
    report: DriftReport,
    output_format: str = "text",
) -> str:
    """Format a DriftReport as text, json, or markdown."""
    if output_format == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)

    if output_format == "markdown":
        lines: List[str] = [
            f"# SchemaPulse Drift Report (`{report.baseline_source}` → `{report.candidate_source}`)",
            "",
            f"- **Baseline Records:** {report.baseline_records}",
            f"- **Candidate Records:** {report.candidate_records}",
            f"- **Total Drift Findings:** {len(report.findings)} "
            f"(Critical: {report.critical_count}, High: {report.high_count})",
            "",
        ]
        if not report.findings:
            lines.append("No schema drift detected.")
            return "\n".join(lines)

        lines.extend(
            [
                "| Rule | Severity | Field Path | Baseline | Candidate | Drift & Remediation |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for f in report.findings:
            lines.append(
                f"| `{f.rule_id}` | **{f.severity.value.upper()}** | `{f.field_path}` "
                f"| `{f.baseline_summary}` | `{f.candidate_summary}` "
                f"| {f.message} — *{f.advice}* |"
            )
        return "\n".join(lines)

    if not report.findings:
        return (
            f"SchemaPulse Diff ({report.baseline_source} -> {report.candidate_source}): "
            f"No schema drift detected across {report.candidate_records} candidate record(s)."
        )

    lines = [
        f"SchemaPulse Drift Report ({report.baseline_source} [{report.baseline_records}] -> "
        f"{report.candidate_source} [{report.candidate_records}])",
        "─" * 86,
    ]
    for f in report.findings:
        sev_tag = f"[{f.rule_id}/{f.severity.value.upper()}]"
        lines.append(
            f"  ! {sev_tag:<18} {f.field_path:<24} {f.baseline_summary} -> {f.candidate_summary}"
        )
        lines.append(f"    └ {f.message}")
        lines.append(f"      Advice: {f.advice}")
    lines.append("─" * 86)
    lines.append(
        f"Summary: {len(report.findings)} drift finding(s) "
        f"(Critical: {report.critical_count}, High: {report.high_count})"
    )
    return "\n".join(lines)


def format_rules_catalog(
    rules: Sequence[DriftRuleSpec],
    output_format: str = "text",
) -> str:
    """Format the built-in drift rules catalog as text, json, or markdown."""
    if output_format == "json":
        return json.dumps([r.to_dict() for r in rules], indent=2, ensure_ascii=False)

    if output_format == "markdown":
        lines = [
            "# SchemaPulse Built-in Drift Rules",
            "",
            "| Rule ID | Severity | Name | Description |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for r in rules:
            lines.append(
                f"| `{r.rule_id}` | **{r.default_severity.value.upper()}** | `{r.name}` | {r.description} |"
            )
        return "\n".join(lines)

    lines = [
        "SchemaPulse Built-in Drift Detection Rules:",
        "─" * 78,
    ]
    for r in rules:
        lines.append(
            f"  {r.rule_id} [{r.default_severity.value.upper():<8}] {r.name}"
        )
        lines.append(f"        {r.description}")
    return "\n".join(lines)
