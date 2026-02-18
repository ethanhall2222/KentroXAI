"""Artifact store utilities for deterministic outputs and templated docs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from trusted_ai_toolkit.schemas import ArtifactManifest, ArtifactManifestItem


class ArtifactStore:
    """Utility for writing artifacts into output_dir/run_id."""

    def __init__(self, output_dir: str | Path, run_id: str, templates_dir: Path | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.run_dir = self.output_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        if templates_dir is None:
            templates_dir = Path(__file__).resolve().parent / "templates"

        self.templates_dir = templates_dir
        self.jinja_env = Environment(loader=FileSystemLoader(str(self.templates_dir)), autoescape=False)

    def path_for(self, name: str) -> Path:
        """Return deterministic path in the active run directory."""

        return self.run_dir / name

    def write_json(self, name: str, payload: dict[str, Any]) -> Path:
        """Write a JSON file artifact."""

        path = self.path_for(name)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def write_jsonl(self, name: str, rows: list[dict[str, Any]]) -> Path:
        """Write a JSONL file artifact."""

        path = self.path_for(name)
        lines = [json.dumps(row, default=str) for row in rows]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def write_md(self, name: str, content: str) -> Path:
        """Write a Markdown file artifact."""

        path = self.path_for(name)
        path.write_text(content, encoding="utf-8")
        return path

    def write_html(self, name: str, content: str) -> Path:
        """Write an HTML file artifact."""

        path = self.path_for(name)
        path.write_text(content, encoding="utf-8")
        return path

    def render_template(self, template_name: str, context: dict[str, Any]) -> str:
        """Render a Jinja2 template from templates/ with context."""

        template = self.jinja_env.get_template(template_name)
        return template.render(**context)

    def save_rendered_md(self, template_name: str, output_name: str, context: dict[str, Any]) -> Path:
        """Render template and persist as markdown."""

        return self.write_md(output_name, self.render_template(template_name, context))

    def save_rendered_html(self, template_name: str, output_name: str, context: dict[str, Any]) -> Path:
        """Render template and persist as html."""

        return self.write_html(output_name, self.render_template(template_name, context))

    def build_manifest(self, required_outputs: list[str]) -> ArtifactManifest:
        """Build manifest for all files in run_dir with completeness metadata."""

        items: list[ArtifactManifestItem] = []
        for path in sorted(self.run_dir.glob("*")):
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stat = path.stat()
            items.append(
                ArtifactManifestItem(
                    path=str(path),
                    sha256=digest,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )
        generated_names = {Path(item.path).name for item in items}
        required_set = set(required_outputs)
        matched = len(required_set.intersection(generated_names))
        completeness = (matched / len(required_set) * 100.0) if required_set else 100.0
        return ArtifactManifest(
            run_id=self.run_id,
            generated_at=datetime.now(timezone.utc),
            items=items,
            required_outputs=required_outputs,
            completeness=round(completeness, 2),
        )

    def write_manifest(self, required_outputs: list[str], filename: str = "artifact_manifest.json") -> Path:
        """Generate and persist artifact manifest as JSON."""

        manifest = self.build_manifest(required_outputs)
        return self.write_json(filename, manifest.model_dump(mode="json"))
