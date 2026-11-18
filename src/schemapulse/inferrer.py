"""Streaming JSONL and JSON array schema lattice inferrer and code generators."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple, Union

from schemapulse.models import FieldProfile, SchemaSnapshot

MAX_ENUM_DISTINCT = 10

_RE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)
_RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_RE_URI = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")


def detect_string_format(value: str) -> str:
    """Classify a string into a semantic format or 'plain'."""
    if _RE_ISO_DATETIME.match(value):
        return "iso-datetime"
    if _RE_ISO_DATE.match(value):
        return "iso-date"
    if _RE_UUID.match(value):
        return "uuid"
    if _RE_EMAIL.match(value):
        return "email"
    if _RE_URI.match(value):
        return "uri"
    return "plain"


def _json_type_of(value: Any) -> str:
    """Return the JSON Schema primitive type name for a Python value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def iter_json_records(target: Union[str, Path]) -> Iterator[Dict[str, Any]]:
    """Stream JSON object records from a .jsonl/.json file or directory of files."""
    path = Path(target)
    files: List[Path] = []
    if path.is_file():
        files.append(path)
    elif path.is_dir():
        for candidate in sorted(path.rglob("*")):
            if candidate.is_file() and candidate.suffix.lower() in {
                ".jsonl",
                ".ndjson",
                ".json",
            }:
                files.append(candidate)
    else:
        raise FileNotFoundError(f"Path not found: {target}")

    for file_path in files:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        yield item
            elif isinstance(parsed, dict):
                yield parsed
            continue

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                yield item


class SchemaLatticeProfiler:
    """Incremental streaming profiler over JSON object records."""

    def __init__(self, source_name: str = "stream") -> None:
        self.source_name = source_name
        self.total_records = 0
        self.fields: Dict[str, FieldProfile] = {}
        self._parent_counts: Dict[str, int] = {"": 0}

    def feed(self, record: Dict[str, Any]) -> None:
        """Profile a single top-level JSON object record."""
        if not isinstance(record, dict):
            return
        self.total_records += 1
        self._profile_object(record, prefix="")

    def _get_field(self, path: str) -> FieldProfile:
        if path not in self.fields:
            self.fields[path] = FieldProfile(path=path)
        return self.fields[path]

    def _profile_object(self, obj: Dict[str, Any], prefix: str) -> None:
        self._parent_counts[prefix] = self._parent_counts.get(prefix, 0) + 1
        for key, value in obj.items():
            field_path = f"{prefix}.{key}" if prefix else str(key)
            fp = self._get_field(field_path)
            fp.present_count += 1
            self._profile_value(fp, value, field_path)

    def _profile_value(self, fp: FieldProfile, value: Any, field_path: str) -> None:
        jtype = _json_type_of(value)
        fp.types_counts[jtype] = fp.types_counts.get(jtype, 0) + 1

        if jtype == "null":
            fp.null_count += 1
            return

        if jtype in ("integer", "number"):
            num_val = float(value)
            if not (math.isnan(num_val) or math.isinf(num_val)):
                if fp.min_number is None or num_val < fp.min_number:
                    fp.min_number = value if isinstance(value, int) else num_val
                if fp.max_number is None or num_val > fp.max_number:
                    fp.max_number = value if isinstance(value, int) else num_val

        if jtype == "string":
            fmt = detect_string_format(value)
            fp.string_formats[fmt] = fp.string_formats.get(fmt, 0) + 1

        if jtype in ("string", "integer", "boolean"):
            if not fp.distinct_overflow:
                if value not in fp.distinct_values:
                    if len(fp.distinct_values) < MAX_ENUM_DISTINCT:
                        fp.distinct_values.append(value)
                    else:
                        fp.distinct_overflow = True

        if jtype == "object" and isinstance(value, dict):
            self._profile_object(value, prefix=field_path)
        elif jtype == "array" and isinstance(value, list):
            elem_path = f"{field_path}[]"
            elem_fp = self._get_field(elem_path)
            for item in value:
                elem_fp.present_count += 1
                self._profile_value(elem_fp, item, elem_path)

    def snapshot(self) -> SchemaSnapshot:
        """Finalize ratios and return an immutable-ready SchemaSnapshot."""
        for path, fp in self.fields.items():
            if path.endswith("[]"):
                parent_seen = fp.present_count
            elif "." in path:
                parent_prefix = path.rsplit(".", 1)[0]
                parent_seen = self._parent_counts.get(parent_prefix, self.total_records)
            else:
                parent_seen = self.total_records

            fp.total_seen = max(parent_seen, fp.present_count)
            if fp.total_seen > 0:
                fp.required_ratio = fp.present_count / fp.total_seen
            else:
                fp.required_ratio = 0.0

            fp.nullable = (fp.null_count > 0) or (fp.present_count < fp.total_seen)

        return SchemaSnapshot(
            source_name=self.source_name,
            total_records=self.total_records,
            fields=dict(sorted(self.fields.items())),
        )


def infer_schema(
    source: Union[str, Path, Iterable[Dict[str, Any]]],
    source_name: Optional[str] = None,
) -> SchemaSnapshot:
    """Infer a SchemaSnapshot from a file path, directory path, or iterable of dicts."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        label = source_name or path.name
        profiler = SchemaLatticeProfiler(source_name=label)
        for record in iter_json_records(path):
            profiler.feed(record)
        return profiler.snapshot()

    profiler = SchemaLatticeProfiler(source_name=source_name or "records")
    for record in source:
        profiler.feed(record)
    return profiler.snapshot()


_FORMAT_TO_JSON_SCHEMA = {
    "iso-datetime": "date-time",
    "iso-date": "date",
    "uuid": "uuid",
    "email": "email",
    "uri": "uri",
}


def to_json_schema(
    snapshot: SchemaSnapshot,
    title: str = "InferredRecord",
) -> Dict[str, Any]:
    """Export an inferred SchemaSnapshot to a Draft 2020-12 JSON Schema document."""

    def _build_field_schema(path: str) -> Dict[str, Any]:
        fp = snapshot.fields.get(path)
        if fp is None:
            return {}

        non_null = sorted(fp.non_null_types)
        has_null = fp.null_count > 0

        if non_null == ["object"]:
            obj_schema = _build_object_schema(prefix=path)
            if has_null:
                obj_schema["type"] = ["object", "null"]
            return obj_schema

        if non_null == ["array"]:
            arr_schema: Dict[str, Any] = {"type": ["array", "null"] if has_null else "array"}
            elem_path = f"{path}[]"
            if elem_path in snapshot.fields:
                arr_schema["items"] = _build_field_schema(elem_path)
            return arr_schema

        schema: Dict[str, Any] = {}
        # Collapse integer + number into number if both occurred
        effective_types = list(non_null)
        if "integer" in effective_types and "number" in effective_types:
            effective_types = [t for t in effective_types if t != "integer"]

        if has_null:
            effective_types.append("null")

        if not effective_types:
            schema["type"] = "null"
        elif len(effective_types) == 1:
            schema["type"] = effective_types[0]
        else:
            schema["type"] = effective_types

        if non_null == ["string"]:
            dom_fmt = fp.dominant_string_format
            if dom_fmt and dom_fmt in _FORMAT_TO_JSON_SCHEMA:
                schema["format"] = _FORMAT_TO_JSON_SCHEMA[dom_fmt]
            elif (
                not fp.distinct_overflow
                and 1 <= len(fp.distinct_values) <= MAX_ENUM_DISTINCT
                and fp.non_null_count >= 2
            ):
                schema["enum"] = list(fp.distinct_values) + ([None] if has_null else [])

        if set(non_null).issubset({"integer", "number"}) and non_null:
            if fp.min_number is not None:
                schema["minimum"] = fp.min_number
            if fp.max_number is not None:
                schema["maximum"] = fp.max_number

        return schema

    def _build_object_schema(prefix: str) -> Dict[str, Any]:
        direct_children: List[Tuple[str, str]] = []
        prefix_dot = f"{prefix}." if prefix else ""
        for path in sorted(snapshot.fields.keys()):
            if path.endswith("[]"):
                continue
            if prefix:
                if not path.startswith(prefix_dot):
                    continue
                rem = path[len(prefix_dot) :]
            else:
                rem = path
            if "." not in rem and "[]" not in rem:
                direct_children.append((rem, path))

        properties: Dict[str, Any] = {}
        required: List[str] = []
        for key, full_path in direct_children:
            properties[key] = _build_field_schema(full_path)
            fp = snapshot.fields[full_path]
            if fp.required_ratio >= 1.0 and fp.null_count == 0:
                required.append(key)

        result: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["required"] = required
        return result

    root = _build_object_schema(prefix="")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        **root,
    }


def _pascal_case(raw: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", raw)
    joined = "".join(p.capitalize() for p in parts if p)
    return joined or "NestedObject"


def to_typed_dict_code(
    snapshot: SchemaSnapshot,
    root_name: str = "Record",
) -> str:
    """Generate Python TypedDict source code from an inferred SchemaSnapshot."""
    class_blocks: List[str] = []
    used_names: Set[str] = set()

    def _alloc_class_name(path: str) -> str:
        if not path:
            used_names.add(root_name)
            return root_name
        clean = path.replace("[]", "_item")
        candidate = _pascal_case(clean)
        if candidate in used_names:
            idx = 2
            while f"{candidate}{idx}" in used_names:
                idx += 1
            candidate = f"{candidate}{idx}"
        used_names.add(candidate)
        return candidate

    def _py_type_for_path(path: str) -> str:
        fp = snapshot.fields.get(path)
        if fp is None:
            return "Any"

        non_null = sorted(fp.non_null_types)
        if "integer" in non_null and "number" in non_null:
            non_null = [t for t in non_null if t != "integer"]

        py_types: List[str] = []
        for t in non_null:
            if t == "string":
                if (
                    fp.dominant_string_format is None
                    and not fp.distinct_overflow
                    and 1 <= len(fp.distinct_values) <= MAX_ENUM_DISTINCT
                    and fp.non_null_count >= 2
                ):
                    literals = ", ".join(repr(v) for v in fp.distinct_values)
                    py_types.append(f"Literal[{literals}]")
                else:
                    py_types.append("str")
            elif t == "integer":
                py_types.append("int")
            elif t == "number":
                py_types.append("float")
            elif t == "boolean":
                py_types.append("bool")
            elif t == "object":
                cls_name = _emit_object_class(path)
                py_types.append(cls_name)
            elif t == "array":
                elem_path = f"{path}[]"
                elem_type = _py_type_for_path(elem_path) if elem_path in snapshot.fields else "Any"
                py_types.append(f"List[{elem_type}]")

        if not py_types:
            base = "None"
        elif len(py_types) == 1:
            base = py_types[0]
        else:
            base = f"Union[{', '.join(py_types)}]"

        if fp.null_count > 0 and base != "None":
            base = f"Optional[{base}]"

        return base

    def _emit_object_class(prefix: str) -> str:
        cls_name = _alloc_class_name(prefix)
        prefix_dot = f"{prefix}." if prefix else ""
        direct_children: List[Tuple[str, str]] = []
        for path in sorted(snapshot.fields.keys()):
            if path.endswith("[]"):
                continue
            if prefix:
                if not path.startswith(prefix_dot):
                    continue
                rem = path[len(prefix_dot) :]
            else:
                rem = path
            if "." not in rem and "[]" not in rem:
                direct_children.append((rem, path))

        field_lines: List[str] = []
        for key, full_path in direct_children:
            fp = snapshot.fields[full_path]
            py_type = _py_type_for_path(full_path)
            if fp.required_ratio < 1.0:
                py_type = f"NotRequired[{py_type}]"
            field_lines.append(f"    {key}: {py_type}")

        if not field_lines:
            field_lines.append("    pass")

        block = f"class {cls_name}(TypedDict):\n" + "\n".join(field_lines)
        class_blocks.append(block)
        return cls_name

    _emit_object_class("")

    header = (
        "from __future__ import annotations\n\n"
        "from typing import Any, List, Literal, NotRequired, Optional, TypedDict, Union\n\n\n"
    )
    return header + "\n\n\n".join(class_blocks) + "\n"
