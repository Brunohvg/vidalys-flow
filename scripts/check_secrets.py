#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private_key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile("gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile("AK" + r"IA[0-9A-Z]{16}"),
    "slack_token": re.compile("xo" + r"x[baprs]-[A-Za-z0-9-]{10,}"),
}


def candidate_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.name == "uv.lock" or path == Path(__file__).resolve():
            continue
        yield path


def main():
    failures = []
    for path in candidate_files():
        content = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                failures.append((path.relative_to(ROOT), label))
    if failures:
        for path, label in failures:
            print(f"FALHA: possível {label} em {path}; valor omitido.")
        return 1
    print("OK: nenhuma assinatura de secret real encontrada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
