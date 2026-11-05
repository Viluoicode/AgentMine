"""C5 CLI composition, explicitly offline; no internal runtime start/finish bypass."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

from test_runtime_operator_cli import CLI
from test_worker_execution_runtime import build_world, usd

from agentmine.application.contracts.records import BudgetCommit
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


class Scenario(TypedDict):
    name: str
    kind: str
    case: str
    minimum: int
    maximum: int
    outcome: str


FIXTURES = Path(__file__).resolve().parents[2] / "contract/fixtures/data_partition_c5"
C3 = FIXTURES.parent / "data_partition_c3"
SCENARIOS = cast(list[Scenario], json.loads((FIXTURES / "scenarios.json").read_text()))


@dataclass
class Simulation:
    cli: CLI
    scenario: Scenario
    expected: Path
    transcript: list[dict[str, object]]

    def command(self, *args: str) -> tuple[int, dict[str, object]]:
        code, data = self.cli.command(*args)
        self.transcript.append({"arguments": list(args), "exit": code, "result": data})
        return code, data

    def prepare(self) -> tuple[int, dict[str, object]]:
        c = self.cli
        return self.command(
            "work",
            "prepare",
            "--opportunity",
            "op",
            "--spec-id",
            "cli-spec",
            "--inputs",
            str(c.manifest),
            "--input-root",
            str(c.root),
            "--facts",
            str(c.facts),
            "--minimum-time-seconds",
            "3600",
            "--evaluation",
            "evaluation",
            "--approve-inputs",
        )

    def execute(self) -> tuple[int, dict[str, object]]:
        return self.command(
            "work",
            "execute",
            "--spec-id",
            "cli-spec",
            "--execution-id",
            "cli-exec",
            "--operation-id",
            "cli-op",
            "--deliverable-id",
            "cli-deliverable",
            "--expected-revision",
            str(self.cli.world.request.expected_opportunity_revision),
            "--confirm",
        )

    def qa(self) -> tuple[int, dict[str, object]]:
        return self.command(
            "work", "qa", "--execution-id", "cli-exec", "--inspection-id", "cli-qa", "--confirm"
        )

    def export(self) -> tuple[int, dict[str, object]]:
        return self.command(
            "work", "export", "--execution-id", "cli-exec", "--directory", str(self.cli.export)
        )

    def save_transcript(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.transcript, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )


def simulation(path: Path, scenario: Scenario) -> Simulation:
    world = build_world(path)
    root = path / "inputs"
    root.mkdir()
    manifest = path / "spec.json"
    if scenario["kind"] == "catalog":
        case = scenario["case"]
        raw = (FIXTURES / (case + "-input.json")).read_bytes()
        sources = [
            dict(
                id="local-input",
                path="input.json",
                sha256=hashlib.sha256(raw).hexdigest(),
                format="json",
                locator="operator:approved-data",
                collected_at=world.clock.now().isoformat(),
            )
        ]
        (root / "input.json").write_bytes(raw)
        columns = json.loads((FIXTURES / "catalog-schema.json").read_text())
        minimum, maximum = 1, 4
        expected = FIXTURES / case
    else:
        case = next(
            c for c in json.loads((C3 / "cases.json").read_text()) if c["name"] == scenario["case"]
        )
        sources = []
        for index, s in enumerate(case["sources"]):
            filename = str(index) + "." + s["format"]
            raw = s["content"].encode("utf-8")
            (root / filename).write_bytes(raw)
            sources.append(
                dict(
                    id=s["reference"],
                    path=filename,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    format=s["format"],
                    locator="fixture:" + s["reference"],
                    collected_at=world.clock.now().isoformat(),
                )
            )
        columns = [
            dict(name="id", path=["id"], case="upper", max_length=4),
            dict(name="title", path=["title"], required=False, case="lower"),
            dict(name="qty", path=["qty"], kind="integer", minimum="0"),
            dict(name="price", path=["price"], kind="decimal", required=False, minimum="0"),
        ]
        minimum, maximum = case["min_records"], case["max_records"]
        expected = C3 / scenario["case"]
    requirements = [
        dict(
            id="requirement:" + c["name"],
            artifact="clean.json",
            kind="column" if scenario["name"] == "b41-null-column" else "field_present",
            criterion=c["name"],
        )
        for c in columns
    ]
    manifest.write_text(
        json.dumps(
            dict(
                sources=sources,
                columns=columns,
                unique_by=["id"],
                min_records=minimum,
                max_records=maximum,
                output_policy=dict(
                    contract_version=2, duplicate_policy="REJECT_ALL", id_column="id"
                ),
                acceptance=dict(
                    formats=[
                        dict(
                            name=n, format="text/csv" if n.endswith(".csv") else "application/json"
                        )
                        for n in ("clean.csv", "clean.json", "rejected.json", "validation.json")
                    ],
                    requirements=requirements,
                    partition_acceptance=dict(
                        contract_version=2,
                        min_clean_records=scenario["minimum"],
                        max_rejected_records=scenario["maximum"],
                    ),
                ),
            )
        ),
        encoding="utf-8",
    )
    facts = path / "facts.json"
    facts.write_bytes((FIXTURES / "facts.json").read_bytes())
    ledger = SQLiteCostLedgerRepository(world.database)
    prior = ledger.get(Reference("ledger"))
    assert prior is not None and not prior.value.records and not prior.value.outstanding
    zero = usd("0")
    ledger.commit(
        BudgetCommit(
            Reference("ledger"),
            Budget(BudgetPolicy(zero, zero, zero, zero), OperatingMode.SCOUT_ONLY),
            prior.revision,
            None,
        )
    )
    return Simulation(CLI(world, root, manifest, facts, path / "export"), scenario, expected, [])
