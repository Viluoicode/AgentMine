import ast
import sys
from pathlib import Path


def test_domain_imports_only_standard_library_or_domain() -> None:
    domain = Path(__file__).resolve().parents[3] / "src" / "agentmine" / "domain"
    sources = list(domain.rglob("*.py"))
    assert sources
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Use explicit domain imports: {source}"
                modules = [node.module or ""]
            for module in modules:
                assert module.split(".")[0] in sys.stdlib_module_names or module.startswith(
                    "agentmine.domain."
                ), f"Forbidden domain dependency {module} in {source}"
