# Superteam OpportunitySource — Milestone 3C

The adapter implements the existing Application `OpportunitySource` port. It uses
only the two read routes verified in [Milestone 3B](marketplace-contracts.md), with
the same documented limitations. No registration, submissions, comments, claims,
LLMs, payment verification or wallet activity is implemented. No new dependency is needed.

## Composition and responsibilities

Explicitly construct `SuperteamOpportunitySource(transport, archive, clock)`:

- `SuperteamHTTP(api_key=...)`: standard-library HTTPS on `superteam.fun`, Bearer key
  supplied by the caller, fixed GET route allowlist, bounded read size and timeout.
  No environment lookup inside infrastructure, redirect following, proxy inheritance,
  credential logging, automatic registration or automatic retries.
- `RawArchive(Path(...))`: successful response bytes, route, timestamp and checksum,
  persisted before decoding. Reuse its file to retain evidence across process restarts.
  Failure to archive prevents normalizing/ingesting that response. Raw bodies remain
  untrusted data and include unknown metadata; they are never executed or logged.
- `Clock`: injected Application clock, providing aware UTC instants.

Use `DiscoverOpportunities(source, repository, clock).execute(DiscoveryRequest(limit))`
for ingestion. The repository may be the existing SQLite adapter. Use `source.inspect`
instead when a caller needs the typed report: normalized batch, raw capture references,
per-item issues/partial eligibility facts, and count of repeated raw rows. It performs
reads and archiving but does not save domain Opportunities. Reports retain UNKNOWN
facts; neither method establishes overall eligibility or creates verified revenue.

## Identity and duplicate ingestion

Opportunity identity remains `superteam:<external-id>`. The source reference remains
`superteam:<slug>` for compatibility with stored 3B observations and the detail route.
An ID repeated with the same slug in a batch is fetched/normalized once. Detail is the
authoritative content; repeated list summaries do not override it. Raw list bytes retain
all repeated rows. Different IDs sharing a slug, or one ID with multiple slugs in one
batch, fail with CONFLICT rather than guessing which identity is authoritative.

Repeated polling uses the same external ID. Existing Application ingestion keeps one
Opportunity and its original observation, preserving advanced lifecycle state/revision.
New raw detail captures still retain changed source content. Different IDs with the same
title remain separate Opportunities. There is no process-global seen-ID cache.

**Slug rename limitation:** a changed slug for an existing external ID causes the existing
Application provenance guard to raise CONFLICT. It does not insert a duplicate or rewrite
original evidence. Automatic slug migration/alias resolution is not part of the verified
contract. Resolve that provenance change explicitly before continuing that record.
Concurrent writers retain existing repository compare-and-swap conflict semantics;
no external exactly-once guarantee or cross-record transaction is introduced.

## Eligibility, missing fields and normalization

The verified Agent API already filters agent-visible listings. The adapter additionally
requires detail `agentAccess` to be `AGENT_ALLOWED` or `AGENT_ONLY` before producing an
observation. `HUMAN_ONLY` is quarantined with AI_PARTICIPATION_PROHIBITED. Absent/new
values keep `facts.ai_policy=UNKNOWN` and AI_POLICY_UNKNOWN; they grant no permission.
Refresh also fails UNSUPPORTED if agent participation is no longer confirmed: the
availability-only port cannot safely express a revoked/unknown AI permission to an
already-eligible workflow. A 404 remains an unavailable read, not proof of closure.

Missing/null title, reward amount, token, compensation model or work text yields explicit
`*_UNKNOWN` normalization issues and no fabricated Opportunity. Missing ID/slug fails
INVALID_RESPONSE because no auditable source identity can be constructed. Malformed
types/numbers/timestamps fail explicitly. Missing/null deadline and unfamiliar status
remain UNKNOWN, never “no deadline” or “open.” Other eligibility facts stay unguessed.

The 3B reward boundary is unchanged: only fixed project offers whose amount/token fit
existing Money can normalize. USDC is not renamed USD; prize pools, negotiated rewards
and unrepresentable assets remain quarantined. Task type is not inferred from a title
or `project` category. These restrictions deliberately prevent unsupported automatic work.

## Pagination and failures

Each call reads one raw window of `min(limit, 50)` and at most one detail per distinct
ID. 3B verified no supported cursor/offset contract. A full **raw** window, even if most
rows are duplicates/quarantined, returns `superteam:pagination-unverified`. Continuation
requests fail UNSUPPORTED before I/O. There is no hidden attempt to call `excludeIds[]`
or an internal endpoint. This adapter does not promise complete marketplace discovery.

Infrastructure `SuperteamReadError` remains an Application `PortError(UNAVAILABLE)` and
adds safe machine fields `reason` and `http_status`. Reasons distinguish authentication
(401), access denial (403), missing source (404), rate limiting (429), redirects, other
HTTP failures and network failures. Response bodies, authentication headers and low-level
exception text are excluded. Connection cleanup runs on success and failure. There is
no guessed GET rate limit or automatic retry/backoff; callers must handle failures explicitly.

Malformed successful JSON is archived before INVALID_RESPONSE. HTTP failures and
oversized responses are not successfully captured bodies. A detail/read/parse failure
fails the batch; the ingestion use case receives no partial batch. Prior raw captures
remain for diagnosis. Existing application multi-row repository writes are not a batch
transaction; concurrent persistence conflicts still need caller reconciliation.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contract tests/unit/test_superteam_smoke.py -p no:cacheprovider
```

Saved fixtures are synthetic examples of the previously verified schema, not live
production captures. Their provenance is in `tests/contract/fixtures/superteam/provenance.json`.
Tests cover unknown/malformed fields, exact amounts, agent permission drift, raw retention,
HTTP errors, duplicate ingestion through reopened SQLite, and smoke-command safeguards.
The root pytest fixture blocks socket connections for all tests; tests mock transports.
The domain test package marker distinguishes its conftest from the root conftest for mypy.

## Optional live smoke probe (explicit invocation only)

This is a separate CLI, never a default pytest test or startup action. First supply an
existing authorized agent key through `AGENTMINE_SUPERTEAM_API_KEY` in the current process
environment using your secret manager or a hidden interactive prompt. Do not place the
key in command arguments, committed files, screenshots or fixtures. `.env` is not loaded.

Then explicitly run:

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.superteam_smoke --live --limit 1 --archive .tmp/superteam-smoke.sqlite3
```

Without `--live`, it exits before environment access, archive creation or HTTP. Missing
or invalid credentials fail before network access. The default window is one listing,
requiring at most two GETs; a limit up to 50 can cause at most 51 GETs. Output is a JSON
summary of normalized/quarantined/duplicate counts, issue codes and capture reference.
Raw bodies stay in the supplied archive; no domain repository is modified.

Exit 0 means the bounded read/inspection succeeded; it does **not** mean any opportunity
is eligible, profitable or submission-ready. An empty list cannot exercise detail
compatibility. Zero normalized records may be legitimate quarantine. Exit 1 indicates
source/archive/normalization failure; exit 2 indicates invocation/configuration failure.
The live probe has not been executed during Milestone 3C implementation. Production
compatibility, complete pagination, token/prize valuation and submission remain unresolved.

## Offline discovery diagnostics - Phase B.3

Use an existing raw archive and exact capture references. This command does not
read an API key, construct HTTP/LLM clients, initialize a workspace or ledger,
ingest opportunities, or perform external actions. No live option exists.

```powershell
.\.venv\Scripts\python.exe -m agentmine.bootstrap.discovery_diagnostics --archive "C:\path\raw.sqlite3" --list-capture "raw:sha256:REPLACE_WITH_64_LOWERCASE_HEX"
```

Add `--detail-capture "raw:sha256:..."` for each explicitly selected detail
(maximum 50 distinct references). The example reference must be replaced with an
actual retained digest. The command never scans for the latest detail or joins
captures by time. Selected list/detail ID, slug and routes must agree; distinct
captures for one listing are a conflict, even if their bodies match.

JSON distinguishes raw rows, unique listings, duplicate rows, normalization,
quarantine and unresolved evidence. NORMALIZED means compatibility with the
current normalizer, not that an Opportunity exists or eligibility was approved.
Bounty and USDC restrictions are unchanged; quarantine issue codes remain visible.
EMPTY_FEED describes only the exact retained list response. UNKNOWN_COVERAGE is
always present: there is no independently proven complete traversal.

PARTIAL_FAILURE concerns selected-evidence inspection, not an inferred historical
API timeout. Missing details remain INCOMPLETE_EVIDENCE, not quarantine or a
network failure. Invalid list evidence fails with unknown counts instead of an
empty-feed result. Verified list metadata is retained on parse/identity errors.
List and detail timestamps are separate; no same-run/freshness claim is made.
Outputs are recomputed using the current normalizer and labeled
`diagnostic_version=offline-discovery-v1`. This is not a historical run journal.

Archive reads use one SQLite read transaction with `mode=ro` (not immutable mode).
Missing files/schema are not initialized. The existing archive writer is unchanged.
To avoid read-created sidecars, WAL and journal-sidecar archives fail closed with
reconciliation required; the tool does not checkpoint, repair, copy or change them.
Stop/resolve archive writer activity separately before inspection. Archives remain
subject to trusted local filesystem/SQLite constraints; arbitrary concurrent file
replacement or journal-mode switching is unsupported.

Bounds: 50 selected details, 2,000,000 body bytes per capture, 8,000,000 aggregate
selected body bytes, list take 1-50, identities at most 256 ASCII identifier
characters. Only bounded identity metadata, capture references/timestamps, typed
reasons and issue codes are rendered; raw title/description/body is not printed.
No new dependency, schema, persistent diagnostic record or financial authority is
introduced. The raw digest verifies retained content integrity, not authenticity.

Exit 0: all selected evidence is resolved, including honest quarantine or empty
feed. Exit 1: incomplete/conflicting/invalid/unavailable evidence. Exit 2: argparse
usage error. Coverage alone does not cause failure. Keep the archive private.
