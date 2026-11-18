# SchemaPulse Engineering Roadmap (200+ Hours)

This roadmap details the planned multi-phase evolution of **SchemaPulse** from a streaming JSONL schema lattice inferrer and silent data drift detector into a full-spectrum data contract intelligence platform covering statistical distribution drift, multi-format columnar/log ingestion, Pydantic/Protobuf/Avro codegen, and CI/CD contract registries.

---

## Phase 1: Core Schema Lattice Profiler, Codegen & Drift Engine (Completed - v0.1.0)
- [x] Core schema lattice data models (`FieldProfile`, `SchemaSnapshot`, `SchemaDriftFinding`, `DriftReport`) in `models.py`.
- [x] Streaming recursive JSONL / JSON array profiler supporting nested objects (`user.address.zip`) and array elements (`items[].price`), semantic string formats (`iso-datetime`, `iso-date`, `uuid`, `email`, `uri`), numeric ranges, and bounded enum domain tracking (`inferrer.py`).
- [x] Draft 2020-12 JSON Schema (`to_json_schema`) and Python `TypedDict` (`to_typed_dict_code`) code generators.
- [x] Foundational drift rules `SP001` (`field-type-mutation`), `SP002` (`required-field-dropped-or-nullable`), `SP003` (`enum-domain-expansion`), `SP004` (`string-format-degradation`), and `SP005` (`undocumented-new-field`) (`differ.py`).
- [x] CLI (`infer`, `diff`, `rules`) with `text`, `json`, `markdown`, `jsonschema`, and `typeddict` formatters.

---

## Phase 2: Statistical & Cardinality Drift Rules (`SP006`–`SP015`) (~40 Hours)
- [ ] **Rule `SP006` (Numeric Range & Quantile Shift):** Track streaming Welford mean/variance and Greenwald-Khanna quantiles ($p_{50}, p_{95}, p_{99}$) to detect silent unit changes (e.g., dollars to cents or milliseconds to seconds).
- [ ] **Rule `SP007` (Null-Rate Spike Detector):** Flag optional fields whose null or missing rate jumps beyond a configurable statistical threshold (e.g., 2% -> 45%) even when the field was already nullable in baseline.
- [ ] **Rule `SP008` (Array Length & Empty-List Collapse):** Track `minItems` / `maxItems` distributions on array paths (`items[]`) and alert when non-empty baseline arrays collapse to empty `[]` lists.
- [ ] **Rules `SP009` – `SP015`:** String length truncation detection (`maxLength` cliff at 255/65535 chars), regex pattern inference for custom IDs (`ORD-[0-9]{6}`), and key-casing drift (`snake_case` -> `camelCase` rename correlation).

---

## Phase 3: Multi-Language & Multi-Target Codegen (`pydantic`, `dataclass`, `proto`, `sql`) (~35 Hours)
- [ ] **Pydantic v2 & Python `dataclass` Generators:** Emit ready-to-import `BaseModel` classes with `Field(ge=..., le=..., pattern=...)` validators and `@dataclass(frozen=True)` definitions.
- [ ] **TypeScript Interface & Zod Schema Exporter:** Generate `.d.ts` interfaces and runtime `z.object({...})` validators from inferred JSONL streams.
- [ ] **Protobuf v3, Apache Avro & DuckDB/PostgreSQL DDL Generators:** Translate inferred schema lattices into `.proto` message definitions, `.avsc` schemas, and `CREATE TABLE` statements with `JSONB` fallback for polymorphic unions.

---

## Phase 4: Discriminated Unions, Polymorphic Lattices & Schema Merging (~40 Hours)
- [ ] **Automatic Discriminator Detection (`type` / `event_type` / `kind`):** Partition heterogeneous JSONL event streams by discriminator key and infer per-variant `oneOf` sub-schemas automatically.
- [ ] **Snapshot Persistence & Lattice Algebra (`schemapulse merge`):** Save compact `.pulse.json` snapshot artifacts in CI and merge daily/hourly partition profiles without re-scanning historical raw data.
- [ ] **Recursive Cross-Field Functional Dependency Finder:** Detect conditional requiredness (e.g., `shipping_address` is required whenever `delivery_method == "physical"`).

---

## Phase 5: Compressed Stream, CSV/TSV & Structured Log Adapters (~45 Hours)
- [ ] **Zero-Copy Compressed Stream Reader:** Stream `.jsonl.gz`, `.jsonl.zst`, `.jsonl.bz2`, and standard input (`cat events.jsonl | schemapulse infer -`) with bounded constant memory.
- [ ] **CSV / TSV & Cloud Log Unwrappers:** Infer nested schemas from stringified JSON columns inside CSV exports, AWS CloudWatch logs, and Kubernetes container stdout envelopes.

---

## Phase 6: Contract Verification Gate, SARIF v2.1.0 & GitHub Action (~40 Hours)
- [ ] **Record-Level Contract Validator (`schemapulse verify <schema.json> <stream.jsonl>`):** Validate millions of streaming JSONL lines against a pinned SchemaPulse snapshot or Draft 2020-12 JSON Schema, reporting exact line numbers and offending payloads.
- [ ] **SARIF v2.1.0 Exporter & PR Comment Bot:** Emit GitHub Code Scanning SARIF reports and side-by-side schema diff tables for pull requests.
