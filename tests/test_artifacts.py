from __future__ import annotations

import json
from pathlib import Path

from trusted_ai_toolkit.artifacts import ArtifactStore


def test_artifact_store_writes_files_and_manifest(tmp_path: Path) -> None:
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "simple.md.j2").write_text("Hello {{ name }}", encoding="utf-8")

    store = ArtifactStore(output_dir=tmp_path / "artifacts", run_id="run123", templates_dir=templates_dir)
    store.write_json("a.json", {"x": 1})
    store.save_rendered_md("simple.md.j2", "a.md", {"name": "world"})

    manifest_path = store.write_manifest(["a.json", "a.md"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_path.exists()
    assert payload["completeness"] == 100.0
    assert len(payload["items"]) >= 2
