import sys
from pathlib import Path

from github_ai_daily.secrets import CommandStore


def test_command_store(tmp_path: Path):
    helper = tmp_path / "secret_helper.py"
    data = tmp_path / "secret.txt"
    helper.write_text(
        "import pathlib,sys\n"
        "p=pathlib.Path(sys.argv[2])\n"
        "op=sys.argv[1]\n"
        "if op=='put': p.write_text(sys.stdin.read())\n"
        "elif op=='get':\n"
        " print(p.read_text(), end='') if p.exists() else sys.exit(1)\n"
        "elif op=='delete': p.unlink(missing_ok=True)\n",
        encoding="utf-8",
    )
    base = f'"{sys.executable}" "{helper}"'
    store = CommandStore(
        f'{base} get "{data}"', f'{base} put "{data}"', f'{base} delete "{data}"'
    )
    store.set("smtp", "secret")
    assert store.get("smtp") == "secret"
    store.delete("smtp")
    assert store.get("smtp") is None
