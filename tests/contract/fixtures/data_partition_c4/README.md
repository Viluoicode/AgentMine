# C4 independent QA expectations

qa-expectations.json contains 27 literal decisions written before production QA
changes. It combines independently retained C2/C3 input/partition facts with
explicit approved minimum-clean and maximum-rejected thresholds. No QA function,
worker, partition function or renderer was invoked to calculate these decisions.
The manifest freezes these expected bytes; never regenerate it from actual QA.

In particular, mixed=clean1/rejected1 passes with maximum2 but not maximum0;
two_duplicates=clean1/rejected2 passes at maximum2 but not maximum0; three
identical IDs leave zero clean rows and never pass. Incomplete coverage and
global issues fail acceptance regardless of partial clean candidates. Optional
null/missing/blank can pass structural FIELD_PRESENT coverage; an explicit COLUMN
non-null requirement remains stricter and is tested separately.

Hostile evidence tests contain literal FAIL assertions even if the attacker
rebinds the bundle digest or coherently re-renders forged canonical values.
Other tests cover typed blocking, immutable inspection recovery and approval
separation. The real SQLite/DataWorker/bootstrap composition is isolated; only
source observations and clock are fakes. This is not live marketplace evidence.
