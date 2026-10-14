# Contract tests

Reserved for conformance tests of concrete adapters against application-owned ports.
Contract validation and Milestone 2B fake-only orchestration are covered in
`tests/unit/application`. Milestone 3A SQLite conformance, atomic writes, round trips
and idempotency are exercised by real-file tests under `tests/integration`. External
adapter contracts remain future work. No external contracts are assumed.
Use documented contracts and sanitized fixtures; never invent an external API.
