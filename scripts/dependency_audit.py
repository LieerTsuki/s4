"""Audit declared dependency licenses; retain notices for release review.

This checks package metadata and lockfiles, not a legal opinion or a complete
binary redistribution audit. CycloneDX artifacts are generated separately by uv/npm.
"""
from __future__ import annotations

import argparse
import json
import re
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\b(?:AGPL|GPL|LGPL)(?:[-\s]|\b)", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/evidence/dependency-licenses.json")
    args = parser.parse_args()
    packages: list[dict[str, str]] = []
    issues: list[str] = []
    for item in distributions():
        metadata = item.metadata
        name = str(metadata["Name"])
        declared = metadata.get("License-Expression") or metadata.get("License") or ""
        classifiers = [value.rsplit(" :: ", 1)[-1] for value in metadata.get_all("Classifier") or [] if value.startswith("License :: OSI Approved ::")]
        # Long License fields are complete notices, not SPDX expressions. Keep
        # their classifier and explicitly flag the notices for release review.
        notice_review = len(declared) > 200
        license_name = "; ".join(classifiers) if notice_review else declared or "; ".join(classifiers)
        if not license_name:
            issues.append(f"python:{name}:license metadata missing")
        elif FORBIDDEN.search(license_name):
            issues.append(f"python:{name}:prohibited declared license")
        packages.append({"ecosystem": "python", "name": name, "version": item.version,
                         "declared_license": license_name, "notice_review": str(notice_review).lower()})
    for relative in ("frontend/package-lock.json", "tests/e2e/package-lock.json"):
        lock_path = ROOT / relative
        if not lock_path.is_file():
            issues.append(f"{relative}:missing lockfile")
            continue
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for path, entry in lock.get("packages", {}).items():
            if not path:
                continue
            license_name = str(entry.get("license", ""))
            if not license_name:
                issues.append(f"{relative}:{path}:license metadata missing")
            elif FORBIDDEN.search(license_name):
                issues.append(f"{relative}:{path}:prohibited declared license")
            packages.append({"ecosystem": "npm", "lockfile": relative, "name": path,
                             "version": entry.get("version", ""), "declared_license": license_name})
    report = {"policy": "reject missing metadata and declared GPL/AGPL/LGPL",
              "scope": "installed Python environment and npm lockfiles; binary notices require release review",
              "packages": packages, "issues": issues, "passed": not issues}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packages": len(packages), "issue_count": len(issues), "issues": issues, "report": str(args.output)}, ensure_ascii=False))
    raise SystemExit(1 if issues else 0)


if __name__ == "__main__":
    main()
