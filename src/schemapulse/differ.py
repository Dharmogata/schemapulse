"""Schema lattice comparison and silent data drift detector (SP001-SP005)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

from schemapulse.inferrer import MAX_ENUM_DISTINCT, infer_schema
from schemapulse.models import (
    DriftReport,
    DriftRuleSpec,
    DriftSeverity,
    FieldProfile,
    SchemaDriftFinding,
    SchemaSnapshot,
)

BUILT_IN_RULES: Tuple[DriftRuleSpec, ...] = (
    DriftRuleSpec(
        rule_id="SP001",
        name="field-type-mutation",
        default_severity=DriftSeverity.CRITICAL,
        description=(
            "Field primitive or structural type changed incompatibly between baseline "
            "and candidate snapshots (e.g., integer -> string)."
        ),
    ),
    DriftRuleSpec(
        rule_id="SP002",
        name="required-field-dropped-or-nullable",
        default_severity=DriftSeverity.HIGH,
        description=(
            "Field that was 100% present and non-null in baseline is now missing "
            "or contains null values in candidate records."
        ),
    ),
    DriftRuleSpec(
        rule_id="SP003",
        name="enum-domain-expansion",
        default_severity=DriftSeverity.MEDIUM,
        description=(
            "Categorical field with a bounded value set introduced new unseen "
            "enum values in candidate records."
        ),
    ),
    DriftRuleSpec(
        rule_id="SP004",
        name="string-format-degradation",
        default_severity=DriftSeverity.MEDIUM,
        description=(
            "String field that consistently matched a semantic format (iso-datetime, "
            "iso-date, uuid, email, uri) degraded to arbitrary plain strings."
        ),
    ),
    DriftRuleSpec(
        rule_id="SP005",
        name="undocumented-new-field",
        default_severity=DriftSeverity.LOW,
        description=(
            "New field path appeared in candidate records that never existed in the "
            "baseline schema snapshot."
        ),
    ),
)


def get_default_rules() -> List[DriftRuleSpec]:
    """Return all built-in SchemaPulse drift rules."""
    return list(BUILT_IN_RULES)


def _format_types_summary(fp: Optional[FieldProfile]) -> str:
    if fp is None:
        return "<missing>"
    types_str = "|".join(sorted(fp.types_counts.keys())) or "unknown"
    return (
        f"types={types_str} "
        f"(present={fp.present_count}/{fp.total_seen}, nulls={fp.null_count})"
    )


def diff_schemas(
    baseline: SchemaSnapshot,
    candidate: SchemaSnapshot,
    min_severity: DriftSeverity = DriftSeverity.LOW,
    select_rules: Optional[Set[str]] = None,
) -> DriftReport:
    """Compare baseline and candidate SchemaSnapshots using rules SP001-SP005."""
    enabled_ids = (
        {r.upper() for r in select_rules}
        if select_rules is not None
        else {r.rule_id for r in BUILT_IN_RULES}
    )
    findings: List[SchemaDriftFinding] = []

    all_paths = sorted(set(baseline.fields.keys()) | set(candidate.fields.keys()))

    for path in all_paths:
        base_fp = baseline.fields.get(path)
        cand_fp = candidate.fields.get(path)

        # SP005: undocumented-new-field
        if base_fp is None and cand_fp is not None:
            if not path.endswith("[]") and "SP005" in enabled_ids:
                findings.append(
                    SchemaDriftFinding(
                        rule_id="SP005",
                        severity=DriftSeverity.LOW,
                        field_path=path,
                        baseline_summary="<missing>",
                        candidate_summary=_format_types_summary(cand_fp),
                        message=f"Undocumented new field `{path}` appeared in candidate stream.",
                        advice="Update downstream schema contracts or filter unexpected producer fields.",
                    )
                )
            continue

        if base_fp is None:
            continue

        # SP002: required-field-dropped-or-nullable
        was_strictly_required = (
            base_fp.required_ratio >= 1.0
            and base_fp.null_count == 0
            and base_fp.present_count > 0
        )
        if not path.endswith("[]") and was_strictly_required and "SP002" in enabled_ids:
            if cand_fp is None or cand_fp.present_count == 0:
                findings.append(
                    SchemaDriftFinding(
                        rule_id="SP002",
                        severity=DriftSeverity.HIGH,
                        field_path=path,
                        baseline_summary=f"required=100% ({base_fp.present_count}/{base_fp.total_seen}), nulls=0",
                        candidate_summary="<missing> (0%)",
                        message=f"Required baseline field `{path}` was completely dropped in candidate records.",
                        advice="Restore the missing field in producer payloads or mark downstream consumers as Optional.",
                    )
                )
            elif cand_fp.required_ratio < 1.0 or cand_fp.null_count > 0:
                cand_req_pct = round(cand_fp.required_ratio * 100, 1)
                findings.append(
                    SchemaDriftFinding(
                        rule_id="SP002",
                        severity=DriftSeverity.HIGH,
                        field_path=path,
                        baseline_summary=f"required=100% ({base_fp.present_count}/{base_fp.total_seen}), nulls=0",
                        candidate_summary=(
                            f"required={cand_req_pct}% "
                            f"({cand_fp.present_count}/{cand_fp.total_seen}), nulls={cand_fp.null_count}"
                        ),
                        message=(
                            f"Previously required non-null field `{path}` is now nullable or partially missing "
                            f"(present {cand_req_pct}%, nulls={cand_fp.null_count})."
                        ),
                        advice="Backfill missing/null values at ingestion or relax `required` / non-null constraints.",
                    )
                )

        if cand_fp is None:
            continue

        # SP001: field-type-mutation
        base_types = base_fp.non_null_types
        cand_types = cand_fp.non_null_types
        if base_types and cand_types and base_types != cand_types and "SP001" in enabled_ids:
            base_type_str = "|".join(sorted(base_types))
            cand_type_str = "|".join(sorted(cand_types))
            findings.append(
                SchemaDriftFinding(
                    rule_id="SP001",
                    severity=DriftSeverity.CRITICAL,
                    field_path=path,
                    baseline_summary=f"type={base_type_str}",
                    candidate_summary=f"type={cand_type_str}",
                    message=(
                        f"Incompatible type mutation on `{path}`: baseline `{base_type_str}` "
                        f"changed to `{cand_type_str}`."
                    ),
                    advice="Enforce strict producer serialization types or bump the event schema version.",
                )
            )

        # SP004: string-format-degradation
        base_fmt = base_fp.dominant_string_format
        if (
            base_fmt is not None
            and "string" in cand_types
            and "SP004" in enabled_ids
        ):
            cand_fmt = cand_fp.dominant_string_format
            plain_count = cand_fp.string_formats.get("plain", 0)
            if cand_fmt != base_fmt or plain_count > 0:
                findings.append(
                    SchemaDriftFinding(
                        rule_id="SP004",
                        severity=DriftSeverity.MEDIUM,
                        field_path=path,
                        baseline_summary=f"format={base_fmt}",
                        candidate_summary=f"format={cand_fmt or 'plain'} (plain_strings={plain_count})",
                        message=(
                            f"Semantic string format on `{path}` degraded from `{base_fmt}` "
                            f"to `{cand_fmt or 'plain'}`."
                        ),
                        advice="Validate string formatting (ISO-8601, UUID, email, URI) before publishing records.",
                    )
                )

        # SP003: enum-domain-expansion
        if (
            base_types == {"string"}
            and cand_types == {"string"}
            and base_fmt is None
            and not base_fp.distinct_overflow
            and 1 <= len(base_fp.distinct_values) <= MAX_ENUM_DISTINCT
            and "SP003" in enabled_ids
        ):
            base_set = set(base_fp.distinct_values)
            new_vals = [v for v in cand_fp.distinct_values if v not in base_set]
            if new_vals or cand_fp.distinct_overflow:
                added_desc = (
                    ", ".join(repr(v) for v in new_vals)
                    if new_vals
                    else ">10 distinct values"
                )
                findings.append(
                    SchemaDriftFinding(
                        rule_id="SP003",
                        severity=DriftSeverity.MEDIUM,
                        field_path=path,
                        baseline_summary=f"enum={sorted(base_fp.distinct_values)}",
                        candidate_summary=(
                            f"added=[{added_desc}]"
                            if not cand_fp.distinct_overflow
                            else "cardinality=>10 (unbounded)"
                        ),
                        message=(
                            f"Categorical field `{path}` expanded its enum domain with unseen value(s): "
                            f"{added_desc}."
                        ),
                        advice="Add the new enum variant(s) to downstream Literal/Enum types and switch statements.",
                    )
                )

    filtered = [f for f in findings if f.severity.rank >= min_severity.rank]
    filtered.sort(key=lambda f: (-f.severity.rank, f.field_path, f.rule_id))

    return DriftReport(
        baseline_source=baseline.source_name,
        candidate_source=candidate.source_name,
        baseline_records=baseline.total_records,
        candidate_records=candidate.total_records,
        findings=filtered,
    )


def diff_sources(
    baseline_source: Union[str, Path, Iterable[Dict[str, object]]],
    candidate_source: Union[str, Path, Iterable[Dict[str, object]]],
    min_severity: DriftSeverity = DriftSeverity.LOW,
    select_rules: Optional[Set[str]] = None,
) -> DriftReport:
    """Infer schemas from two sources and run the drift detector."""
    base_snap = infer_schema(baseline_source)
    cand_snap = infer_schema(candidate_source)
    return diff_schemas(
        base_snap,
        cand_snap,
        min_severity=min_severity,
        select_rules=select_rules,
    )
