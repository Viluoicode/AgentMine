# Contract tests

Reserved for conformance tests of concrete adapters against application-owned ports.
Contract validation and Milestone 2B fake-only orchestration are covered in
`tests/unit/application`; no concrete
adapter exists yet. Atomic writes, round trips and idempotency require future
adapter tests. No external contracts are assumed.
Use documented contracts and sanitized fixtures; never invent an external API.
