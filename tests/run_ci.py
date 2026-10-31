"""Executa a suíte offline e gera relatórios consumidos pelo CI e Sonar."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
COVERAGE_DATA = REPORTS / ".coverage"
PYTEST_TEMP = REPORTS / ".pytest-tmp"
SOURCE = "app"


def _run_coverage(*arguments: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "coverage", *arguments],
        cwd=ROOT,
        check=False,
    ).returncode


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    test_status = _run_coverage(
        "run",
        "--data-file",
        str(COVERAGE_DATA),
        "--branch",
        f"--source={SOURCE}",
        "-m",
        "pytest",
        "-q",
        "tests",
        f"--junitxml={REPORTS / 'junit.xml'}",
        f"--basetemp={PYTEST_TEMP}",
    )
    xml_status = _run_coverage(
        "xml", "--data-file", str(COVERAGE_DATA), "-o", str(REPORTS / "coverage.xml")
    )
    html_status = _run_coverage(
        "html", "--data-file", str(COVERAGE_DATA), "--directory", str(REPORTS / "htmlcov")
    )
    report_status = _run_coverage("report", "--data-file", str(COVERAGE_DATA))
    shutil.rmtree(PYTEST_TEMP, ignore_errors=True)
    return test_status or xml_status or html_status or report_status


if __name__ == "__main__":
    raise SystemExit(main())
