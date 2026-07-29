#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXECUTABLE_SUFFIXES = {".py", ".sh"}
EXECUTABLE_NAMES = {"Dockerfile"}

FORBIDDEN_SYMBOLS = (
    "apps." + "tenants",
    "Tenant" + "Middleware",
    "request." + "tenant",
    "Global" + "Settings",
    "account_" + "origin",
    "VIDALYS_" + "RUNTIME_MODE",
    "django_" + "q",
    "q" + "cluster",
    "apps." + "billing",
    "apps." + "customers",
    "apps." + "orders",
    "apps." + "payments",
    "apps." + "boletos",
    "apps." + "integrations",
    "apps." + "notifications",
    "apps." + "api",
    "apps." + "marketing",
    "apps." + "restock",
    "apps." + "abandoned_checkouts",
    "apps." + "discounts",
    "apps." + "ai",
    "customers" + "_v2",
    "orders" + "_v2",
    "payments" + "_v2",
    "integrations" + "_v2",
)


def executable_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path == Path(__file__).resolve():
            continue
        if path.suffix in EXECUTABLE_SUFFIXES or path.name in EXECUTABLE_NAMES:
            yield path


def violations():
    found = []
    for path in executable_files():
        content = path.read_text(encoding="utf-8", errors="ignore")
        for symbol in FORBIDDEN_SYMBOLS:
            if symbol in content:
                found.append((path.relative_to(ROOT), symbol))
    return found


def main():
    found = violations()
    if found:
        for path, symbol in found:
            print(f"FALHA: símbolo proibido em {path}: {symbol}")
        return 1
    print("OK: código executável independente; nenhum símbolo proibido encontrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
