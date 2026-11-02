"""Toda ferramenta dos agentes precisa de um rótulo de progresso, senão o SSE fica sem a mensagem."""

import glob
import re

from app.observability import progress


def _tool_names() -> set[str]:
    names: set[str] = set()
    for path in glob.glob("app/tools/**/*.py", recursive=True):
        text = open(path, encoding="utf-8").read()
        names |= set(re.findall(r"@tool[^\n]*\n\s+def ([a-z_]+)\(", text))
    return names


def test_every_agent_tool_has_a_progress_label():
    missing = _tool_names() - set(progress._TOOL_LABELS)
    assert not missing, f"Ferramentas sem rótulo no SSE: {sorted(missing)}"


def test_labels_are_plain_language():
    for label in progress._TOOL_LABELS.values():
        assert "_" not in label and label[0].isupper()
