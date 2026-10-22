"""Static import boundaries, including imports nested inside functions/type guards."""

import ast
import sys
from pathlib import Path

import pytest


def forbidden_imports(source: str, layer: str) -> list[str]:
    allowed: tuple[str, ...] = (f"agentmine.{layer}",)
    if layer == "application":
        allowed += ("agentmine.domain",)
    if layer == "presentation":
        allowed += ("agentmine.application", "agentmine.domain")
    if layer == "infrastructure":
        allowed += ("agentmine.application", "agentmine.domain")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                violations.append("relative import")
                continue
            module = node.module or ""
            modules = (
                [f"{module}.{alias.name}" for alias in node.names]
                if module in ("agentmine", "agentmine.application", "agentmine.domain")
                else [module]
            )
        for module in modules:
            root = module.split(".")[0]
            if layer in ("domain", "application") and root in (
                "sqlite3",
                "http",
                "urllib",
                "socket",
                "importlib",
            ):
                violations.append(module)
            elif layer == "infrastructure" and root != "agentmine":
                continue  # Vendor/driver dependencies belong in adapters.
            elif root not in sys.stdlib_module_names and not any(
                module == prefix or module.startswith(prefix + ".") for prefix in allowed
            ):
                violations.append(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if layer in ("domain", "application") and node.func.id == "__import__":
                violations.append("dynamic import")
    return violations


@pytest.mark.parametrize("layer", ["domain", "application", "presentation", "infrastructure"])
def test_inner_layers_obey_import_direction(layer: str) -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "agentmine" / layer
    sources = list(root.rglob("*.py"))
    assert sources
    for source in sources:
        assert not forbidden_imports(source.read_text(encoding="utf-8"), layer), str(source)


@pytest.mark.parametrize(
    "source",
    [
        "import agentmine.infrastructure.adapter",
        "from agentmine import infrastructure",
        "from agentmine.presentation import api",
        "from agentmine.bootstrap.config import Settings",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n import boto3",
        "def hidden():\n import requests",
        "from ..infrastructure import adapter",
    ],
)
def test_application_guard_detects_forbidden_imports(source: str) -> None:
    assert forbidden_imports(source, "application")


def test_application_can_depend_on_domain_but_domain_cannot_depend_on_application() -> None:
    assert not forbidden_imports("from agentmine.domain.work import Task", "application")
    assert forbidden_imports("from agentmine.application.ports import services", "domain")


def test_presentation_cannot_construct_infrastructure_or_bootstrap() -> None:
    assert forbidden_imports("from agentmine.infrastructure.dynamodb import store", "presentation")
    assert forbidden_imports(
        "from agentmine.bootstrap.dynamodb import dynamodb_repositories", "presentation"
    )


@pytest.mark.parametrize("layer", ["domain", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "import sqlite3",
        "from http.client import HTTPSConnection",
        "import urllib.request",
        "import socket",
        "import importlib as loader",
        "__import__('agentmine.infrastructure')",
    ],
)
def test_standard_library_does_not_exempt_inner_layer_io(source: str, layer: str) -> None:
    assert forbidden_imports(source, layer)


def test_infrastructure_points_inward_and_may_use_drivers() -> None:
    assert not forbidden_imports("import boto3\nimport sqlite3", "infrastructure")
    assert not forbidden_imports(
        "from agentmine.application.ports.repositories import OpportunityRepository",
        "infrastructure",
    )
    assert forbidden_imports("from agentmine.bootstrap import local", "infrastructure")
    assert forbidden_imports("from agentmine.presentation import operator_cli", "infrastructure")


def dependency_cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    completed: set[str] = set()
    cycles: list[tuple[str, ...]] = []

    def visit(module: str, path: tuple[str, ...]) -> None:
        if module in path:
            cycles.append((*path[path.index(module) :], module))
            return
        if module in completed:
            return
        for dependency in sorted(graph[module]):
            visit(dependency, (*path, module))
        completed.add(module)

    for module in sorted(graph):
        visit(module, ())
    return cycles


def test_production_import_graph_has_no_cycles() -> None:
    root = Path(__file__).resolve().parents[2] / "src"
    modules = {
        ".".join(path.relative_to(root).with_suffix("").parts).removesuffix(".__init__"): path
        for path in root.rglob("*.py")
    }
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, path in modules.items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Explicit imports required: {path}"
                imports = [node.module or ""] + [
                    f"{node.module}.{alias.name}" for alias in node.names
                ]
            graph[module].update(name for name in imports if name in modules)
    assert not dependency_cycles(graph)


def test_cycle_guard_detects_indirect_cycles() -> None:
    assert dependency_cycles({"a": {"b"}, "b": {"c"}, "c": {"a"}})
    assert not dependency_cycles({"a": {"b", "c"}, "b": {"c"}, "c": set()})


def test_operator_presentation_has_no_repository_dependencies() -> None:
    path = Path(__file__).resolve().parents[2] / "src/agentmine/presentation/operator_cli.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("agentmine.application.ports")
            assert node.module != "agentmine.application.use_cases.context"
