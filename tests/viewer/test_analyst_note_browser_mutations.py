from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_browser_mutation_identity_survives_uncertain_response_and_replays() -> None:
    node = shutil.which("node")
    assert node, "Node.js is required to execute the browser mutation contract"
    result = subprocess.run(
        [node, str(ROOT / "tests/viewer/analyst_note_mutations_contract.js")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_company_page_sends_stable_note_and_operation_identity() -> None:
    template = (ROOT / "tools/viewer/templates/industry_companies.html").read_text(
        encoding="utf-8"
    )
    assert "new HonghuAnalystNoteMutations.MutationCoordinator(window.sessionStorage)" in template
    assert "'X-Idempotency-Key':identity.operation_id" in template
    assert "note_key:identity.note_key" in template
    assert "create:company:" in template
