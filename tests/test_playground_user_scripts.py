"""Confere idempotência e isolamento dos scripts mongosh com coleções controladas."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js necessário para executar o JavaScript dos scripts mongosh.")
@pytest.mark.parametrize("scenario", ["empty", "legacy", "existing_preferences", "wrong_connection"])
def test_mongo_fixture_migration_preserves_records_and_can_be_repeated(scenario):
    result = subprocess.run(
        [NODE, "tests/playground_user_scripts.cjs", scenario],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
