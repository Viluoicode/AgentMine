# Submission System (Milestone 5B)

SubmitTask accepts API, MANUAL or UNSUPPORTED mode. All modes require the current
human-approved deliverable, passing QA and matching destination/content. Mode is part
of the immutable intent. No adapter or credentials are selected implicitly.

## Modes

- API calls the injected SubmissionGateway once after a durable claim. Repeated calls
  reuse a confirmed result or call observation-only reconcile for uncertain effects.
  Reconcile must never create a submission. A missing API gateway fails before claiming.
- MANUAL returns a retained ManualSubmissionPackage with target, exact approved content,
  deliverable/version and operator instructions. It makes no gateway call. Package creation
  yields HUMAN_ACTION_REQUIRED and leaves the opportunity APPROVED_FOR_SUBMISSION.
- UNSUPPORTED records an explicit unsupported result without calling the gateway or source.
  It does not advance the opportunity or imply that anything was sent.

A gateway can be None for manual/unsupported composition. API remains the default for
existing callers. Mode/target are trusted composition/operator choices, not inferred from
bounty prose. This milestone does not implement a marketplace POST adapter.

## Manual workflow

Call `SubmitTask.execute(opportunity_id, submission_id, SubmissionMode.MANUAL)` after
approval. The returned `manual_package.content.text` is the approved content; worker
bundles contain their named artifacts. Render/export these exact bytes for the operator
alongside `target`, `deliverable`, `reference` and `instructions`. The package is a typed
application result, not a new GUI, ZIP exporter or file-writing service.

The operator checks current listing status/deadline and existing receipts before sending
through the supported marketplace interface. Never resend a package whose prior outcome
is uncertain. After sending, call RecordManualSubmission with the opportunity/submission
IDs, actual submission time, evidence reference, external ID when available, marketplace
response and optional URL. Its configured operator identity is retained as recorded_by.
The receipt is explicitly operator-reported, not independently authenticated. Time must
be between approval and now. Receipt recording does not contact the marketplace and can
recover evidence of a historical send even after the listing closes.

The operator must send the approved bytes to the approved destination. AgentMine prevents
local duplicate intents/receipts, but cannot prevent a person clicking an external button
twice. A package alone never marks SUBMITTED. Recorded receipt moves only to SUBMITTED;
acceptance/rejection and verified payment still require their separate existing workflows.

## Recorded evidence

SubmissionResult retains status, observed_at, optional external_submission_id,
marketplace_response and external_url. A confirmed domain Submission carries the actual
submitted_at time, exposed as submission_timestamp. Unconfirmed results have no invented
submission time or ID. Marketplace response is a text snapshot; JSON may be retained as
text. Adapters must remove credentials/private data before returning it; raw responses
are not logged. Only HTTP(S) external URL references are accepted; none are fetched.
Legacy results explicitly retain unknown metadata as None.

Statuses: CONFIRMED means receipt of submission, not accepted work; HUMAN_ACTION_REQUIRED
means operator work remains; UNKNOWN requires reconciliation; FAILED means an explicit
provider refusal; UNSUPPORTED means no supported mechanism. FAILED is a submission-attempt
status and never becomes the domain's marketplace outcome REJECTED.

## Idempotency and persistence

The repository atomically grants one claim per submission ID AND per deliverable
reference/version, across modes and destinations. Changing the ID cannot obtain another
claim for that version. Identical writes are idempotent and changed intent payloads conflict.
SQLite checks legacy and current rows inside one write transaction; test fakes implement
the same contract. Scanning submission intents is acceptable for the current local dataset.

Responses persist before confirmed receipts and opportunity transitions. Retrying repairs
partial persistence without another send or needless reconciliation. Unknown provider
exceptions and invalid responses retain UNKNOWN evidence with safe error messages. If
saving that evidence also fails, the durable intent still blocks another dispatch.
Concurrent conflicting confirmations are rejected atomically; the first confirmation is
retained. Confirmed results take precedence over earlier manual packages/unknown attempts.

There is no blind retry of a known FAILED/UNSUPPORTED result and no implicit API-to-manual
fallback. A different submission mechanism or corrected payload requires an explicit
future recovery/review process; this milestone does not implement cancellation/release of
submission intents. Do not work around a pending intent by changing its key.

The SQLite codec supports a narrow additive migration: pre-5B requests load as API and
pre-5B results load with unknown metadata. Other missing/unknown fields remain errors.
Existing aggregate shapes and database schema remain unchanged. Older application versions
cannot read new snapshots; no downgrade migration is provided.

## Offline tests and live prerequisites

Default tests use fakes and temporary SQLite files, with network blocked. They cover
approval enforcement, all modes, retries, timeouts, invalid responses, partial persistence,
metadata retention, manual receipt conflicts, different-key/concurrent duplicates and
legacy snapshot loading. No account, key or paid call is needed to run pytest.

No real marketplace submission was performed. The existing marketplace contract matrix
still leaves receipt binding and reconciliation/idempotency unresolved for a production
Superteam submission adapter. Before a live API test, verify that contract, implement its
gateway, and select an operator-approved test opportunity/destination with the required
account permissions. Credentials must be configured locally, never pasted into chat.
For a manual live test, the operator needs an approved deliverable and authorized marketplace
account, then must supply the receipt details after sending. Live external submission is
not part of the automated tests or this implementation run.
