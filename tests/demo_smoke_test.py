from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_demo_prep_generates_consistent_bundle(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "demo_prep.sh"

    output_root = tmp_path / "demo_outputs"
    env = os.environ.copy()
    env["DEMO_OUTPUT_ROOT"] = str(output_root)
    env["DEMO_CONFIG_PATH"] = str(repo_root / "configs" / "demo_config.yaml")
    env["DEMO_CONTEXT_PATH"] = str(repo_root / "configs" / "demo_context.json")

    subprocess.run(["bash", str(script_path)], cwd=repo_root, env=env, check=True)

    latest_bundle = (output_root / "latest").resolve()
    assert latest_bundle.exists()

    scorecard_path = latest_bundle / "scorecard.json"
    manifest_path = latest_bundle / "artifact_manifest.json"
    eval_results_path = latest_bundle / "eval_results.json"
    redteam_path = latest_bundle / "redteam_findings.json"

    assert scorecard_path.exists()
    assert manifest_path.exists()

    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    eval_results = json.loads(eval_results_path.read_text(encoding="utf-8"))
    redteam = json.loads(redteam_path.read_text(encoding="utf-8"))

    assert manifest["completeness"] == scorecard["evidence_completeness"]
    assert scorecard["system_context"] is not None
    assert eval_results["system_context"] is not None
    assert redteam["system_context"] is not None

    expected_hash = scorecard["system_context"]["system_hash"]
    assert eval_results["system_context"]["system_hash"] == expected_hash
    assert redteam["system_context"]["system_hash"] == expected_hash
