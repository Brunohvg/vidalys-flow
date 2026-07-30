import ast
from pathlib import Path

from scripts.check_independence import violations


def test_executable_code_is_independent():
    assert violations() == []


def test_domain_services_and_selectors_require_explicit_organization():
    for domain in ("customers", "products", "orders"):
        for module in ("services.py", "selectors.py"):
            path = Path("apps") / domain / module
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                    continue
                arguments = {argument.arg for argument in (*node.args.args, *node.args.kwonlyargs)}
                assert "organization" in arguments, f"{path}:{node.name} deve receber organization"
