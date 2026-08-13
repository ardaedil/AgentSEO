"""Version the sealed Phase 1.5B manifest after a pre-holdout evaluator correction."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from agentseo.phase15b_benchmark import PHASE15B_EVALUATOR_VERSION

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "phase15b"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    manifest_path = ARTIFACT_ROOT / "holdout_manifest.json"
    protocol_path = ARTIFACT_ROOT / "protocol_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if manifest.get("task_count") != 40 or len(manifest.get("tasks", [])) != 40:
        raise RuntimeError("Refusing to alter a manifest that is not the sealed 40-task holdout")
    manifest["evaluator_version"] = PHASE15B_EVALUATOR_VERSION
    manifest["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    for task in manifest["tasks"]:
        task["evaluator_version"] = PHASE15B_EVALUATOR_VERSION
    protocol["holdout_manifest_sha256"] = canonical_hash(manifest)
    protocol["evaluator_version"] = PHASE15B_EVALUATOR_VERSION
    protocol["evaluator_correction"] = (
        "Refusal text takes precedence over question-mark clarification; B20/C20 explanation-and-stop "
        "does not require an invalid or unsupported tool call. Task IDs and initial-state hashes unchanged."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    protocol_path.write_text(json.dumps(protocol, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "evaluator_version": PHASE15B_EVALUATOR_VERSION,
                "holdout_task_count": manifest["task_count"],
                "holdout_manifest_sha256": protocol["holdout_manifest_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
