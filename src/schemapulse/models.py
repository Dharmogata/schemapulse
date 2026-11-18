"""Core data models for SchemaPulse schema lattice profiling and data drift detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class DriftSeverity(str, Enum):
    """Severity classification for schema drift findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            DriftSeverity.LOW: 1,
            DriftSeverity.MEDIUM: 2,
            DriftSeverity.HIGH: 3,
            DriftSeverity.CRITICAL: 4,
        }[self]


@dataclass(frozen=True)
class DriftRuleSpec:
    """Metadata specification for a built-in schema drift rule."""

    rule_id: str
    name: str
    default_severity: DriftSeverity
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "default_severity": self.default_severity.value,
            "description": self.description,
        }


@dataclass
class FieldProfile:
    """Profiled schema lattice statistics for a single nested JSON path."""

    path: str
    total_seen: int = 0
    present_count: int = 0
    null_count: int = 0
    types_counts: Dict[str, int] = field(default_factory=dict)
    string_formats: Dict[str, int] = field(default_factory=dict)
    distinct_values: List[Any] = field(default_factory=list)
    min_number: Optional[float] = None
    max_number: Optional[float] = None
    required_ratio: float = 0.0
    nullable: bool = False
    distinct_overflow: bool = False

    @property
    def non_null_types(self) -> Set[str]:
        return {t for t, c in self.types_counts.items() if t != "null" and c > 0}

    @property
    def non_null_count(self) -> int:
        return sum(c for t, c in self.types_counts.items() if t != "null")

    @property
    def dominant_string_format(self) -> Optional[str]:
        """Return a semantic string format if >= 90% of strings match it."""
        str_count = self.types_counts.get("string", 0)
        if str_count == 0 or not self.string_formats:
            return None
        best_fmt, best_count = max(
            self.string_formats.items(), key=lambda kv: kv[1]
        )
        if best_fmt != "plain" and (best_count / str_count) >= 0.9:
            return best_fmt
        return None

    @property
    def is_enum_candidate(self) -> bool:
        """True if field has scalar values, <= 10 distinct values, and no semantic format."""
        if self.distinct_overflow or not self.distinct_values:
            return False
        if len(self.distinct_values) > 10:
            return False
        allowed = {"string", "integer"}
        if not self.non_null_types or not self.non_null_types.issubset(allowed):
            return False
        if self.dominant_string_format is not None:
            return False
        # Require either multiple observations per value or small domain
        return len(self.distinct_values) <= 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "total_seen": self.total_seen,
            "present_count": self.present_count,
            "null_count": self.null_count,
            "types_counts": dict(sorted(self.types_counts.items())),
            "string_formats": dict(sorted(self.string_formats.items())),
            "distinct_values": list(self.distinct_values),
            "min_number": self.min_number,
            "max_number": self.max_number,
            "required_ratio": round(self.required_ratio, 4),
            "nullable": self.nullable,
            "dominant_string_format": self.dominant_string_format,
        }


@dataclass
class SchemaSnapshot:
    """Complete inferred schema snapshot across a stream of JSON records."""

    source_name: str
    total_records: int
    fields: Dict[str, FieldProfile] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "total_records": self.total_records,
            "total_fields": len(self.fields),
            "fields": {
                k: v.to_dict() for k, v in sorted(self.fields.items())
            },
        }


@dataclass(frozen=True)
class SchemaDriftFinding:
    """Represents a single schema or semantic data drift violation between two snapshots."""

    rule_id: str
    severity: DriftSeverity
    field_path: str
    baseline_summary: str
    candidate_summary: str
    message: str
    advice: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "field_path": self.field_path,
            "baseline_summary": self.baseline_summary,
            "candidate_summary": self.candidate_summary,
            "message": self.message,
            "advice": self.advice,
        }


@dataclass
class DriftReport:
    """Aggregated drift report comparing baseline and candidate schema snapshots."""

    baseline_source: str
    candidate_source: str
    baseline_records: int
    candidate_records: int
    findings: List[SchemaDriftFinding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == DriftSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == DriftSeverity.HIGH)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_source": self.baseline_source,
            "candidate_source": self.candidate_source,
            "baseline_records": self.baseline_records,
            "candidate_records": self.candidate_records,
            "total_findings": len(self.findings),
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "findings": [f.to_dict() for f in self.findings],
        }
