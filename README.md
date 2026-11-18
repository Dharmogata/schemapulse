# SchemaPulse

**SchemaPulse** is a command-line streaming JSONL schema lattice inferrer, Draft 2020-12 JSON Schema & Python `TypedDict` code generator, and silent data drift detector (`SP001`–`SP005`).

Data pipelines, webhook consumers, and LLM structured-output workflows frequently break not from syntax errors, but from **silent schema drift**: an integer ID suddenly serialized as a string, a 100%-required field turning nullable, a status enum gaining an undocumented `"chargeback_pending"` state, or ISO-8601 timestamps degrading into free-form text. SchemaPulse profiles nested JSONL/JSON streams in a single pass, generates ready-to-use type definitions, and catches breaking data drift in CI.

---

## Who It's For

- **Backend, data, and platform engineers** inferring strict schemas (`JSON Schema` or Python `TypedDict`) from raw production `.jsonl` event dumps, API logs, or webhook fixtures.
- **Data reliability and CI maintainers** gating pull requests or ingestion jobs against silent producer drift (`schemapulse diff baseline.jsonl candidate.jsonl --fail-on-drift`).

---

## What It's Built With

- **Language:** Python 3.10+
- **Core Architecture:** Pure Python standard library (`json`, `re`, `math`, `argparse`, `pathlib`, `dataclasses`, `unittest`) with **zero external runtime dependencies**.
- **Test Suite:** Compatible with both `pytest` and `python -m unittest`.

---

## Features

- **Recursive Lattice Profiling:** Streams `.jsonl`, `.ndjson`, and `.json` files or directories, profiling arbitrary nested objects (`user.address.zip`) and array elements (`items[].price`).
- **Semantic Format & Domain Inference:** Automatically detects `iso-datetime`, `iso-date`, `uuid`, `email`, and `uri` string formats, numeric `[min, max]` bounds, required ratios, nullability, and bounded enum candidates.
- **Zero-Dependency Codegen:** Exports inferred profiles directly to **Draft 2020-12 JSON Schema** (`--format jsonschema`) or Python **`TypedDict`** source code (`--format typeddict`).
- **Built-in Drift Detection Rules (`SP001` – `SP005`):**
  - `SP001` (`CRITICAL` / `field-type-mutation`): Field type changed incompatibly between baseline and candidate (e.g., `integer` -> `string`).
  - `SP002` (`HIGH` / `required-field-dropped-or-nullable`): Field that was 100% present and non-null in baseline is now missing or null in candidate records.
  - `SP003` (`MEDIUM` / `enum-domain-expansion`): Categorical field with a stable small value set introduced new unseen enum values (e.g., `status` added `"chargeback_pending"`).
  - `SP004` (`MEDIUM` / `string-format-degradation`): Field that consistently matched a semantic format (`iso-datetime`, `uuid`, `email`) in baseline degraded to arbitrary plain strings.
  - `SP005` (`LOW` / `undocumented-new-field`): New field path appeared in candidate records that never existed in baseline.

```text
$ schemapulse diff baseline.jsonl candidate.jsonl --fail-on-drift

SchemaPulse Drift Report (baseline.jsonl [2] -> candidate.jsonl [1])
──────────────────────────────────────────────────────────────────────────────────────
  ! [SP001/CRITICAL]   order_id                 type=integer -> type=string
    └ Incompatible type mutation on `order_id`: baseline `integer` changed to `string`.
      Advice: Enforce strict producer serialization types or bump the event schema version.
  ! [SP002/HIGH]       customer_id              required=100% (2/2), nulls=0 -> required=100.0% (1/1), nulls=1
    └ Previously required non-null field `customer_id` is now nullable or partially missing (present 100.0%, nulls=1).
      Advice: Backfill missing/null values at ingestion or relax `required` / non-null constraints.
  ! [SP004/MEDIUM]     created_at               format=iso-datetime -> format=plain (plain_strings=1)
    └ Semantic string format on `created_at` degraded from `iso-datetime` to `plain`.
      Advice: Validate string formatting (ISO-8601, UUID, email, URI) before publishing records.
  ! [SP003/MEDIUM]     status                   enum=['paid', 'pending'] -> added=['chargeback_pending']
    └ Categorical field `status` expanded its enum domain with unseen value(s): 'chargeback_pending'.
      Advice: Add the new enum variant(s) to downstream Literal/Enum types and switch statements.
  ! [SP005/LOW]        debug_trace              <missing> -> types=string (present=1/1, nulls=0)
    └ Undocumented new field `debug_trace` appeared in candidate stream.
      Advice: Update downstream schema contracts or filter unexpected producer fields.
──────────────────────────────────────────────────────────────────────────────────────
Summary: 5 drift finding(s) (Critical: 1, High: 1)
```

---

## How to Run It

### 1. Install

```bash
git clone https://github.com/Dharmogata/schemapulse.git
cd schemapulse
pip install -e .
```

### 2. Infer Schemas & Generate Code

```bash
# Profile a JSONL file or directory and print a terminal lattice table
schemapulse infer events.jsonl

# Export Draft 2020-12 JSON Schema
schemapulse infer events.jsonl --format jsonschema

# Generate Python TypedDict definitions
schemapulse infer events.jsonl --format typeddict
```

### 3. Detect Silent Data Drift

```bash
# Compare baseline and candidate JSONL streams
schemapulse diff baseline.jsonl candidate.jsonl

# Fail CI on HIGH or CRITICAL drift and output Markdown for PR comments
schemapulse diff baseline.jsonl candidate.jsonl --min-severity high --format markdown --fail-on-drift

# List all built-in drift rules (SP001-SP005)
schemapulse rules
```

### 4. Run the Test Suite

```bash
# Using pytest
pytest -v

# Or using standard library unittest
PYTHONPATH=src python -m unittest discover -s tests -v
```

---

## Planned Work Ahead (TODO & Roadmap)

SchemaPulse has **200+ hours of planned engineering work** detailed in [ROADMAP.md](ROADMAP.md):

- [ ] **Phase 2 (~40h): Statistical & Cardinality Drift Rules (`SP006`–`SP015`)** (streaming Welford/quantile shift detection for unit changes, optional field null-rate spike alerts, array length collapse, and custom ID regex inference).
- [ ] **Phase 3 (~35h): Multi-Language & Multi-Target Codegen** (Pydantic v2 `BaseModel`, Python `@dataclass`, TypeScript interfaces, Zod validators, Protobuf v3, and DuckDB/PostgreSQL DDL).
- [ ] **Phase 4 (~40h): Discriminated Unions, Polymorphic Lattices & Schema Merging** (`oneOf` discriminator partitioning on `event_type`, `.pulse.json` snapshot merging, and cross-field functional dependency detection).
- [ ] **Phase 5 (~45h): Compressed Stream, CSV/TSV & Structured Log Adapters** (streaming `.jsonl.gz` / `.zst`, stdin piping, and CloudWatch/Kubernetes log envelope unwrapping).
- [ ] **Phase 6 (~40h): Contract Verification Gate (`schemapulse verify`), SARIF v2.1.0 Exporter & GitHub Action**.

See [ROADMAP.md](ROADMAP.md) for the complete specification.

---

## License

Released under the [MIT License](LICENSE).
