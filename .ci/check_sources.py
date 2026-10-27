"""Sintaxe de Python/JSON rastreados e whitespace. Nao importa a aplicacao."""
import ast
import json
import os
from pathlib import Path
import subprocess


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    errors = []
    for name in filter(None, names):
        path = Path(name)
        if not path.is_file():
            continue
        try:
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=name)
            elif path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, ValueError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
    base = os.environ.get("BASE_SHA", "")
    if base and set(base) != {"0"}:
        args = ["git", "diff", "--check", base, "HEAD"]
    else:
        args = ["git", "show", "--format=", "--check", "HEAD"]
    if subprocess.run(args, check=False).returncode:
        errors.append("Whitespace invalido no diff")
    if errors:
        raise SystemExit("\n".join(errors))
    print("OK: sintaxe Python/JSON e whitespace; nenhuma aplicacao foi executada.")


if __name__ == "__main__":
    main()
