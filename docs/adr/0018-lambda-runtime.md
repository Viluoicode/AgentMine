# ADR 0018: Thin Lambda callables with explicit dependency factories

Status: Implemented for requested Milestone 6C scope.

## Decision

Presentation validates versioned direct/custom EventBridge input, resolves a use case through
an injected callable, maps a small result and logs correlation metadata. Bootstrap composes
four existing use cases from repository/service ports on each invocation. No business rules,
SDK selection or hidden mutable cache enters handlers. No Domain/Application changes.

## Consequences

Discovery, normalization, outcome tracking and payment observation are independently invocable.
Errors raise sanitized exceptions so asynchronous failures are visible; AWS retry/DLQ policy
is deployment-owned. Existing use-case/repository idempotency applies, without promising
exactly-once delivery. Missing external bindings fail explicitly. Live source archival and
gateway/verifier contracts must be resolved before production wiring. No AWS deployment or
new dependencies are included. See [runtime contracts](../lambda-runtime.md).

## Alternatives

Putting lifecycle loops in handlers violates dependency direction. Returning successful error
dictionaries can silently acknowledge failed async work. Global mutable dependency caches,
event-selected adapter imports and a new generic orchestration framework are unnecessary.
