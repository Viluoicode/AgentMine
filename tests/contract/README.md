# Contract tests

Milestone 3B tests verify the limited Superteam source against existing application ports.
Fixtures under `fixtures/superteam` are **synthetic**, based on official documented
routes and pinned public-source schemas. `provenance.json` records their origin and
limitations. They are not authenticated production captures or real opportunities.
Algora/Opire have no invented fixtures because no current external schema was verified.

- `test_superteam_normalization.py`: exact decimals, potential-only rewards, unknown
  eligibility/deadlines, blocked prize/asset mappings, invalid and future fields.
- `test_superteam_source.py`: bounded discovery/detail, raw retention, quarantine,
  identity correlation, existing use-case injection and disabled source skeletons.
- `test_marketplace_transport_archive.py`: fixed read-only origin/routes, no redirects
  or retry, safe auth/rate/network failures, size bounds and durable raw captures.

All transport tests mock the connection; source tests inject offline bytes. Temporary
SQLite files need writable pytest temporary storage. Run `python -m pytest tests/contract
-p no:cacheprovider`. No key, account, network or paid call is used. Existing repository
conformance tests remain under `tests/integration`.

Review [the contract matrix](../../docs/marketplace-contracts.md) before updating fixtures.
For future real captures, remove credentials/PII and explicitly record provenance;
do not represent a synthetic example as a recorded API response. Production activation
requires a separate authenticated read-only smoke test and review of remaining gaps.

Milestone 3C extends these tests with duplicate rows, re-ingestion after SQLite reopen,
preserved lifecycle/provenance, ambiguous identity conflicts, revoked/unknown agent
participation and machine-readable HTTP failures. Additional saved fixtures deliberately
exercise duplicate/missing fields without claiming those are production captures.
`tests/unit/test_superteam_smoke.py` tests the optional CLI with offline transports.
The root `tests/conftest.py` blocks socket connections throughout pytest; a domain test
package marker keeps its conftest distinct for strict mypy checking.
See [the explicit live probe instructions](../../docs/superteam-source.md); no default
test reads a production key or calls a live API.
