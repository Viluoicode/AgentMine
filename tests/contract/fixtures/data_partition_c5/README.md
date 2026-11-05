# C5 independent E2E and B.4.1 oracle provenance

All scenarios are synthetic/offline, not real bounty or client-acceptance evidence.
`scenarios.json` contains 16 literal decisions specified before runtime changes.
C3 scenarios reuse immutable C3 literal artifact goldens, not generated output.

The four `*-input.json` files and `catalog-schema.json` retain the exact approved
B.4.1 facts/schema from `.tmp/phase-b4-simulation`; facts.json is its synthetic
eligibility input. `legacy-complete/` retains pre-C1 v1 artifact bytes from that
simulation, not freshly rendered expectations. No original files were changed.

The dirty/control/complete/malformed directories hold 13 expected v2 artifacts.
They were specified before production changes using only stdlib JSON/CSV/hashlib
and the earlier independent normalized-value facts, with these explicit rules:

- Dirty row1 and row3 duplicate A001: both reject (Policy A).
- Row2 has missing name, invalid+missing category, invalid+missing price, negative
  stock: six reasons. Row4 lacks ID/stock: missing_column+missing_value for each.
- Total dirty=12 issues, 4 rejected, 0 clean; the v1 total of 11 is not reused.
- Brand absent becomes output null with MISSING provenance, without imputation.
- Malformed input preserves unknown source count, diagnostic-only output and
  global record_count plus actual malformed_source issue.

The preparation imported no AgentMine code and invoked no worker, partition,
renderer or QA. Canonical bytes follow the approved C3 serialization contract:
UTF-8 no BOM, JSON LF/sorted keys/indent2/no final newline; CSV LF/minimal quoting,
compact provenance and the existing formula-prefix escaping.

A Windows text-write mistake initially introduced CRLF into seven expected JSON
files. After the first GREEN attempt, only those line endings were corrected to
the predeclared C3 LF contract; no JSON value, input byte, threshold, membership,
issue or approved decision changed. Actual output was not used to generate the
oracle. The correction hashes are retained in ignored `.tmp/c5-oracle-newline-fix.json`.
`sha256.json` freezes fixture bytes; this README is intentionally excluded.

CLI test composition is real; only source observations and clock are injected
as test fakes. Production CLI has no fake-provider switch or fallback. All
workspaces are isolated; no submission/payment or production database mutation.
