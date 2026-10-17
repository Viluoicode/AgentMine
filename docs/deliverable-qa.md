# Deliverable QA (Milestone 4D)

`DeliverableQA` is an explicitly invoked application use case for ResearchWorker and
DataWorker outputs. It depends only on inner-layer contracts and ports. No submission
port is available to it. No additional dependency or external API is introduced.

## Inputs and order

The trusted caller loads the approved worker plan and retained result, declares required
artifacts and acceptance criteria, and builds `QAInspection`. Persist `bundle_content(result)`
through ExecutionRepository and use its SHA-256 reference in the versioned Deliverable
before finishing the opportunity. Invoke `DeliverableQA.execute(inspection)` when QA_PENDING.
Criteria are explicit COLUMN, SECTION (exact heading), LITERAL or SEMANTIC checks. They
must come from task requirements, not be chosen by the model reviewing its own output.
Changing criteria requires a new inspection reference and leaves the old audit intact.

1. Deterministic: bind the exact stored bundle and version; check required artifact names,
   media types, bounded nonempty content, strict JSON/CSV or Markdown title, and declared
   requirement coverage. A failed check stops later stages.
2. Domain-specific: research checks approved source inventory, locator/tool/time provenance,
   quoted facts against verified captured text, minimum verified sources, separated facts,
   analysis and uncertainties, and reproducible artifacts. Data checks reproduce deterministic
   transformations, record identity/provenance, optional semantic evidence, schema constraints,
   duplicates, counts, canonical values, and CSV/JSON/validation agreement.
3. AI: only explicit semantic criteria or semantically transformed data fields trigger review.
   It requires a separate persisted QA budget authorization and injected LLMProvider. Free
   checks must pass first. Existing structured provider schema and untrusted-content boundary
   apply. A model cannot override failed free checks or authenticate an unverified source.

## Results and transitions

| Outcome | Meaning | Lifecycle |
| --- | --- | --- |
| PASS | All required checks pass | READY_FOR_HUMAN_REVIEW |
| FAIL | Integrity/provenance or unsupported claim failure | IN_PROGRESS for rework |
| NEEDS_REVISION | Missing content, invalid format/constraints or negative AI review | IN_PROGRESS for rework |
| REQUIRES_HUMAN_REVIEW | Unresolved verification, unavailable budget/reviewer or uncertain AI outcome | Remains QA_PENDING |

PASS never creates HumanApproval or invokes SubmitTask. RequestHumanApproval,
ApproveSubmission and SubmitTask remain separate existing use cases. New deliverable
versions are required after rework. An unresolved inspection can be superseded by a new
inspection after its cause is resolved; the old report is immutable.

Each QAReport binds deliverable/version/content, timestamp and ordered findings. Every
finding has a machine-readable code, outcome, explanation and evidence references.
Aggregation priority is FAIL, NEEDS_REVISION, REQUIRES_HUMAN_REVIEW, PASS.
The existing binary QAResult remains the terminal lifecycle assessment: PASS maps to
PASSED, rework outcomes map to FAILED. Unresolved reports do not create a terminal
QAResult. RunQA remains the existing trusted explicit-assessment recording entry point;
callers wanting automated checks invoke DeliverableQA instead.

## Persistence and recovery

QAJournal owns immutable inspections, reports, AI dispatch claims and responses.
SQLiteQAJournal implements it using the existing local snapshot store and codec registry;
no cloud infrastructure or schema migration is needed. Reports persist before lifecycle
updates; repeating an identical inspection repairs an interrupted transition. Changed
payloads under the same ID conflict. AI claims use the authorization operation ID, so a
second inspection cannot silently reuse a dispatched authorization. Retained responses
permit recovery after cost/report persistence failure without another paid call.
A claimed operation with no response requires reconciliation; it is never blindly retried.

Known usage is recorded even if model advice fails validation, including actual cost above
estimate. Unknown usage stays explicit and leaves its reservation outstanding. Budget
failure or deadline expiry before AI dispatch yields human review; free QA still works.

## Limitations

Coverage is against declared criteria, not an automatic proof that all natural-language
requirements were captured. Trusted callers must supply authoritative persisted plans,
results and criteria. Captured source provenance is not independent verification of truth;
research analysis remains unverified unless semantic review is requested. AI advice remains
fallible. JSON/CSV checks cover the V1 worker contracts, not arbitrary document formats.
No user interface, live evidence fetcher, automatic repair loop or external submission is
added. Unknown provider outcomes and charges require operator reconciliation. New automated
QA is an explicit composition point; existing CLI/demo workflows are not silently rewired.

## Offline verification

Unit tests cover ordering, outcomes, integrity, missing fields/formats, unsupported facts,
data consistency, budget denial, unknown usage, actual over estimate, and persistence
recovery. SQLite integration tests cover reopening immutable evidence and claim conflicts.
All providers are fakes/mock; default tests block network access.
