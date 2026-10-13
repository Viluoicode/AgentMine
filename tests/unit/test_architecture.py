"""Static import boundaries, including imports nested inside functions/type guards."""

import ast
import sys
from pathlib import Path

import pytest


def forbidden_imports(source: str, layer: str) -> list[str]:
    allowed: tuple[str, ...] = (f"agentmine.{layer}",)
    if layer == "application":
        allowed += ("agentmine.domain",)
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
            if module.split(".")[0] not in sys.stdlib_module_names and not any(
                module == prefix or module.startswith(prefix + ".") for prefix in allowed
            ):
                violations.append(module)
    return violations


@pytest.mark.parametrize("layer", ["domain", "application"])
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
