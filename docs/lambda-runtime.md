# AWS Lambda runtime adapter — Milestone 6C

Lambda is a transport/runtime boundary. Domain/Application code is unchanged, and no
handler authorizes spending, changes lifecycle rules, calculates scores, grants human
approval, executes paid work or verifies payments itself. No resource is deployed.

## Minimal workflow handlers

| Handler callable | Input | Existing application use case |
| --- | --- | --- |
| `handlers.discover(event, context)` | Bounded discovery request | DiscoverOpportunities |
| `handlers.normalize(event, context)` | Opportunity ID | NormalizeOpportunity |
| `handlers.track_outcome(event, context)` | Submitted opportunity ID | TrackOutcome |
| `handlers.verify_payment(event, context)` | Accepted opportunity ID | VerifyPayment |

Discovery is suitable for a scheduled invocation with explicit custom input. The other
handlers consume one opportunity command at a time. There is no scheduler, table-scanning
poller, fan-out, SQS batch protocol, HTTP/API Gateway facade or automatic workflow chain.
Selection of due opportunities and publishing follow-up commands remain outside this adapter.
One discovery invocation fetches one bounded page and returns an opaque continuation;
it does not loop or assume that a source supports pagination.

## Wiring and Lambda handler exports

Bootstrap owns `LambdaDependencies` and `create_lambda_handlers(factory)`. The factory receives
the fixed Workflow enum, not the event, and returns injected repository/service ports. It
runs after input validation on every invocation. This keeps environment, credentials,
SDK construction and adapter selection outside Presentation and prevents events from
selecting a database, endpoint, import path or credentials. There is no global client cache,
service locator or implicit environment lookup.

The returned frozen `LambdaHandlers` exposes standard two-argument callables. Export them
from the deployment's module for AWS Handler configuration, for example:

```python
from agentmine.bootstrap.lambda_runtime import create_lambda_handlers
from deployment_wiring import resolve_ports

handlers = create_lambda_handlers(resolve_ports)
discover_handler = handlers.discover
normalize_handler = handlers.normalize
track_outcome_handler = handlers.track_outcome
verify_payment_handler = handlers.verify_payment
```

For a file named `entrypoints.py`, configure `entrypoints.discover_handler`, etc.
`deployment_wiring` above is an explicit deployment-owned module, not a module shipped
or dynamically imported by AgentMine. It supplies `LambdaDependencies` from existing
ports. For example, it can inject opportunity/submission repositories from
`dynamodb_repositories(client, table)`, an explicit Clock and configured source/gateway/
verifier. Constructing the handler bundle does not call the factory or contact AWS.
The immutable exported callables hold wiring, not cached invocation data or credentials.

All four workflows run with fake services in tests. Missing required external ports raise
`runtime_not_configured`; no mock or guessed production API is silently substituted.
Normalization requires only opportunity persistence and the common dependency container.
Production discovery also needs an explicitly configured source with durable raw metadata
retention. Existing Superteam local SQLite raw archival is not silently moved to Lambda
ephemeral `/tmp`. Production submission/outcome/payment service contracts remain unresolved
as documented in earlier milestones. Implementing those bindings is separate work.

## Event contracts

Direct discovery input (also usable as a scheduler's custom target input):

```json
{"schema_version": 1, "correlation_id": "discovery-2026-10-19", "limit": 20}
```

`limit` defaults to 20 and must be an integer 1–100; booleans are rejected. An optional
`continuation` is a bounded nonblank opaque string. The 100-item boundary limits invocation
size, not a promise that every marketplace supports it. Source-specific limits remain
the source adapter's responsibility.

Opportunity commands for the other three handlers:

```json
{"schema_version": 1, "correlation_id": "job-123", "opportunity_id": "op-123"}
```

Custom EventBridge envelope:

```json
{
  "source": "agentmine",
  "detail-type": "agentmine.normalize",
  "id": "event-123",
  "detail": {"schema_version": 1, "opportunity_id": "op-123"}
}
```

Detail types are `agentmine.discover`, `agentmine.normalize`, `agentmine.track_outcome`
and `agentmine.verify_payment`, and must match the selected handler. Metadata outside
`detail` is not forwarded to use cases. Bare AWS Scheduled Event envelopes without custom
AgentMine input are not inferred into commands. `source` and schema validation are not
authentication; invocation permissions belong to deployment infrastructure.

Unknown detail/input fields and unsupported schema versions are rejected before dependency
resolution. IDs are required for opportunity commands; the event cannot supply outcomes,
payment proofs, approval decisions, task descriptions or database/provider configuration.

## Results, correlation and safe failures

Success returns JSON-serializable `ok`, `workflow`, `correlation_id`, `request_id`, `data`.
Discovery data has IDs, count and continuation. Other data has opportunity ID and lifecycle
state. Full aggregates, deliverables, source metadata and configuration are not returned.

Correlation uses explicit input correlation ID, then valid EventBridge event ID, then the
Lambda request ID. If context is absent/invalid during local calls, generate a UUID. Logged
IDs are limited to 128 ASCII letters/digits/`._:-`; newline/control characters are rejected.
Request ID remains separate from correlation ID. Correlation is for observability, never
a substitute for business idempotency keys or authorization.

Structured JSON log messages record start/success or sanitized failure, workflow and both
IDs. Configure the deployment's logger/Lambda log level to INFO to retain successful records;
handlers do not mutate global logging configuration. No event body, exception text, stack
locals, environment, credentials or arbitrary provider response is logged by this boundary.

All failures raise `InvocationFailure` with a JSON message and suppressed original exception
context. This is deliberate: returning an ordinary error dictionary would acknowledge an
asynchronous invocation as successful. Invalid transport input maps to `invalid_event`;
missing bindings to `runtime_not_configured`; known domain/application/port errors retain
their machine code; unexpected exceptions map to `internal_error`. Provider error text and
configuration values are excluded. UNAVAILABLE/CONFLICT are marked retryable metadata;
OUTCOME_UNKNOWN explicitly requires reconciliation. The handler does not retry internally.

AWS may retry any raised asynchronous failure regardless of the metadata; configure retry
limits, event age and failure destinations during deployment. This milestone creates none.
Pending outcomes/payments are successful observations, not raised failures or invented
acceptance/revenue. Reinvocation cadence remains the caller's responsibility.

## Replay and limits

Existing repositories/use cases retain idempotency: duplicate discovery preserves the source
and aggregate revision, same-phase normalization is idempotent, and completed outcome/payment
checks reuse stored evidence. There is no new generic event receipt table. A stale normalize
command replayed after the lifecycle advanced can fail INVALID_TRANSITION; it cannot downgrade
the aggregate. No exactly-once delivery guarantee is claimed. Retries of unresolved observations
can poll again; the adapter does not fabricate a terminal outcome to suppress retries.

The runtime performs one synchronous application call. Timeout, memory, package size, IAM,
schedule/event bus, deployment manifests and operational failure destinations require later
deployment configuration. No new dependency, cloud service, SDK import in Presentation, or
inner-layer contract change is introduced.

## Validation and operator actions

Run `python -m pytest tests/unit/test_lambda_runtime.py tests/integration/test_lambda_dynamodb.py`
with the project environment. DynamoDB integration uses the existing optional Moto test extra.
Tests block network and spend $0. No user action, credential or live AWS account is needed.
Coverage includes strict events/envelopes, bounded discovery and cursor propagation, per-call
dependency resolution, replay persistence, acceptance versus paid, sanitized errors, correlation
logs, configuration failures and Presentation import guards.

Official runtime references:
[Python handler contract](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html),
[async retries and duplicate delivery](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html).

## Execution report — 2026-10-19

All commands used the existing `.venv\Scripts\python.exe` environment.

| Check | Result |
| --- | --- |
| `-m pytest tests/unit/test_lambda_runtime.py -q --tb=short -p no:cacheprovider` | 35 passed |
| `-m pytest -q -p no:cacheprovider` | 889 passed in 25.61 seconds, including Lambda/DynamoDB integration and Presentation guards |
| `-m ruff check .` | Passed |
| `-m ruff format --check .` | 215 files already formatted |
| `-m mypy` | Passed, 169 source files |
| `git diff --check` | Passed |

38 tests were added relative to Milestone 6B. No paid API call, user credential, real
payment or AWS deployment was involved. No new dependency or inner-layer change.
