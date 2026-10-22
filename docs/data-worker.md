 # DataWorker — Milestone 4C

## Scope and architecture

`DataWorker.execute(DataPlan) -> DataResult` implements the application-owned
`Worker[DataPlan, DataResult]` port. Worker now has explicit plan/result type parameters;
ResearchWorker remains `Worker[TaskPlan, ResearchResult]`. Domain is unchanged.

Data processing uses standard-library code. There is no new dependency, live source API,
scraping, file discovery, submission, tool execution or automatic bootstrap activation.
The caller supplies approved source content, a validated DATA_PROCESSING Execution and
an explicit declarative DataPlan. Existing ExecuteTask/lifecycle orchestration is unchanged.

The worker does not infer eligibility, approve submissions, change an Opportunity or
create verified revenue. Before new execution or resumption, the calling application
retains responsibility for opportunity freshness, eligibility, scoring and lifecycle rules.

## Supported processing

| Capability | V1 behavior |
| --- | --- |
| Structured collection | Combine up to 10 explicitly supplied CSV/JSON source snapshots in declared order |
| Extraction | Map output columns to tuple paths through JSON objects or exact CSV header names |
| Categorization | Explicit key/value lookup tables; unknown keys are invalid, never guessed |
| Normalization | Trim text; explicit lower/upper case; canonical integers, decimals, booleans and ISO dates |
| Validation | Required columns/values, types, allowed values, length, numeric bounds, duplicates, counts and declared cross-column comparisons |
| Enrichment | Local lookup tables with required evidence references; optional designated semantic fields |

JSON input must be an array of objects. CSV uses a unique, nonempty header and fixed row
width; extra/missing cells, malformed quoting and duplicate headers fail. JSON duplicate
keys and nonfinite numbers fail. Extraction traverses object keys, not arrays or executable
expressions. Missing paths are distinguished from missing values. Unmapped input fields
remain in the retained source snapshot; they are intentionally absent from output columns.

Values are canonical strings or null. JSON numbers are read without binary floating-point
rounding. Numeric columns accept plain decimal notation, not scientific notation or locale
separators. Numeric lexical values are bounded to 1000 characters. Booleans accept true/false;
dates require YYYY-MM-DD and calendar validity. Null and whitespace-only values are missing.
Malformed nested values cannot silently become text. No imputation or heuristic date guessing.

Columns have identifier names (not reserved `row_id` or `_...`), source paths, a type,
required flag, case normalization, optional lookup/evidence, allowed values, numeric bounds,
and maximum text length. Lookup keys match after trim/case normalization. Lookup values are
then type-normalized and validated. Lookup evidence identifies caller-approved policy/data;
it is not externally verified by the worker.

Task-specific constraints are declarative: equality or numeric less-or-equal between named
columns, in addition to per-column bounds/enumerations and dataset count/uniqueness rules.
There is no arbitrary expression, regex, code evaluation, fuzzy matching or plugin execution.

## Validation and output policy

Configured record count is inclusive, 0–1000. The hard processing bound is 1000 records;
an oversized collection returns RECORD_COUNT failure, never a silently truncated success.
At most 50 columns and 50 cross-column constraints are supported. Each source is bounded
to 1,000,000 UTF-8 bytes; paths have at most 10 components.

Duplicates are checked on normalized `unique_by` columns, or on the whole output row when
no key is configured. Rows are retained and flagged, not silently dropped or merged.
Missing optional values remain null. Empty datasets may be allowed with min_records=0;
CSV required headers are still validated. Required JSON paths are checked per record.

Validation issues carry stable codes plus source reference, logical row number and column
where applicable: MALFORMED_SOURCE, MISSING_COLUMN, MISSING_VALUE, INVALID_VALUE,
DUPLICATE, RECORD_COUNT and CONSTRAINT (enum values lowercase).

A valid result contains:

- `data.csv`: configured columns plus `_provenance` containing JSON metadata.
- `data.json`: array of records with values and nested `_provenance`.
- `validation.json`: validity, processed record count and issues.

An invalid result retains available typed records/issues for diagnosis and produces only
`validation.json`; it does not export a dataset as successful. Input malformed/oversized
sources cannot contribute valid rows. Invalid deterministic data prevents AI dispatch.

Artifacts are reusable text values with SHA-256 digests; the worker does not choose paths
or write arbitrary files. CSV quoting handles commas/newlines. Formula-looking CSV values
beginning with =, +, - or @ after whitespace are prefixed with an apostrophe; this applies
also to negative numeric strings. JSON retains exact normalized strings/nulls and is the
canonical lossless output. CSV empty cells represent null. Consumers needing exact values
should use JSON rather than undoing CSV protection heuristically.

## Provenance

Each record retains source ID, locator, collection time, exact input SHA-256 and one-based
logical source row (excluding the CSV header). Each field retains its extraction path,
lookup evidence and optional model-operation evidence. The immutable plan retains all
source bytes and transformation rules for audit/reconstruction.

Source metadata is supplied by the caller and explicitly marked unverified. A digest is
content integrity evidence, not authenticity. Semantic values always remain unverified;
model output cannot replace source IDs, provenance, record IDs or deterministic fields.
No generated URLs become sources. Source timestamps in the future are rejected.

## Optional semantic assistance

The default path needs no LLM provider and makes zero model calls. Only TEXT columns with
an explicit nonblank `semantic_reason` can request AI interpretation; deterministic lookup
and semantic interpretation cannot be combined on the same column. The operator must
justify that the field genuinely needs semantic interpretation. Bad deterministic values
never trigger an AI repair fallback.

The worker sends only source text for designated fields, their interpretation requirements,
allowed values and stable row IDs through the existing WorkRequest/LLMProvider port. Other
deterministic columns are not included as semantic input. Optional fields without source
text stay null without a model call. The batch is bounded to 50,000 bytes before dispatch;
there is no hidden paid batching or automatic retry.

Responses must satisfy the existing 4A data schema (plan/rows/evidence), then stricter local
rules: exact requested row IDs and field sets, no missing/extra/duplicate rows, string/null
values, no duplicate JSON keys, and evidence aliases bound to the supplied inputs. Row order
may differ; IDs determine correlation. A model plan is never executed. AI can fill only
explicit semantic fields, and all ordinary value/uniqueness/task constraints run afterwards.
Its claims remain uncertain even when schema and category validation pass. Bedrock's existing
untrusted-content separation and secret checks remain in infrastructure.

## Cost and recovery

Compose `DataWorker(budget_manager, data_journal, llm=None)` for deterministic processing.
The execution must have a persisted zero-cost AI authorization for this path, so it also
runs under SCOUT_ONLY. This records zero AI usage, not zero infrastructure cost. Local CPU,
storage and previously incurred source-acquisition costs are not measured here; the result
explicitly warns `infrastructure_cost_not_measured`.

For semantic processing, supply the optional LLMProvider and an appropriate persisted
estimate/authorization. Current budget is checked before paid calls. Denial causes no model
call; existing lifecycle orchestration owns WAITING_FOR_BUDGET and revalidation. Known
actual AI cost is correlated to execution/scope/category/currency/estimate/time and recorded
idempotently. Overruns are retained with warnings and existing ledger audit issues.
Unknown actual cost remains unknown with its reservation; estimates never become actuals.
If validation prevents AI entirely, the known AI cost is zero and the reservation is settled.

`DataJournal` requires immutable plans, one-owner semantic dispatch claims, saved responses
and final results. `SQLiteDataJournal` uses existing SQLite snapshots/transactions. Reuse a
durable journal across workers. Changed plans cannot reuse an execution identity. Provider
responses are retained before worker accounting, and known cost is recorded before model
schema validation. Rejected model responses can still cost money.

A cached response/result can recover failed ledger/result writes without another model
call, including completing local recovery after the deadline. A new dispatch after the
deadline is rejected. A claim with no response is OUTCOME_UNKNOWN and requires manual
reconciliation; timeouts and failed response persistence are never automatically retried.
Journal and ledger are separate transactions, not exactly-once external billing. Retained
source/model data needs private local storage; there is no new encryption/retention system.

## Tests

Unit tests use memory journals and fake LLMs. Integration tests reopen SQLite journals and
ledgers, verify deterministic/semantic replay, handle interrupted accounting and compete for
a single dispatch claim. Network is blocked by the existing suite fixture. No automated test
calls a production model, source, billing or submission API.
