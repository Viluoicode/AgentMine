# Integration tests

Milestone 3A exercises real temporary SQLite files without network or paid API calls.

- test_local_workflow.py runs the same 13 use cases with memory and SQLite repository
  ports, for both supported task types, reopening SQLite adapters between steps.
- test_local_persistence.py covers complete snapshots, access patterns, exact financial
  reports, budget restoration, competing writers/claims, rollback and corrupt data.
- local_cases.py supplies public-domain-action fixtures and protocol-typed composition.

Run `python -m pytest tests/integration -p no:cacheprovider` with the project environment.
Pytest needs access to its temporary directory. Service/provider fakes are reused from
`tests/unit/application` through the test-only pythonpath setting in pyproject.toml.
