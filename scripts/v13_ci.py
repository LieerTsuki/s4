"""Local GitLab shell-runner verification, isolated from developer resources.

Prerequisites: Linux, Python3.11, Node24/npm, locked-compatible uv, Docker Compose,
and Gitleaks. This is not the unprovided main repository's five-gate definition.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_name() -> str:
    if os.environ.get("CI") != "true" or os.name == "nt":
        raise RuntimeError("This provisioner runs only on the dedicated Linux CI runner")
    pipeline, job = os.environ.get("CI_PIPELINE_ID", ""), os.environ.get("CI_JOB_ID", "")
    if not re.fullmatch(r"[0-9]+", pipeline) or not re.fullmatch(r"[0-9]+", job):
        raise RuntimeError("CI job identity is missing")
    return f"s4-ci-{pipeline}-{job}"


def command(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def compose(*args: str) -> None:
    command("docker", "compose", "-p", project_name(), "--env-file", ".env",
            "-f", "deploy/compose.yml", "-f", "deploy/compose.dev.yml", *args)


def bootstrap() -> None:
    project_name()
    destination = ROOT / ".env"
    owner, application = secrets.token_hex(32), secrets.token_hex(32)
    values = {
        "S4_DB_OWNER_PASSWORD": owner, "S4_DB_APP_PASSWORD": application,
        "S4_DATABASE_URL": f"postgresql+asyncpg://s4_app:{application}@127.0.0.1:55434/s4_dev",
        "S4_MIGRATION_DATABASE_URL": f"postgresql+asyncpg://s4_owner:{owner}@127.0.0.1:55434/s4_dev",
        "S4_TEST_DATABASE_URL": f"postgresql+asyncpg://s4_owner:{owner}@127.0.0.1:55434/s4_test",
        "S4_DATA_DIR": str(ROOT / "var"), "S4_COOKIE_SECURE": "false",
        "S4_ALLOWED_ORIGIN": "http://localhost:5176", "S4_EXTERNAL_ALIGNMENT_CONFIRMED": "false",
        "S4_LEGACY_WRITES_ENABLED": "false",
    }
    # Never overwrite an existing checkout's credentials or point at its database.
    with destination.open("x", encoding="utf-8") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in values.items()))
    destination.chmod(0o600)
    (ROOT / "var/evidence").mkdir(parents=True, exist_ok=True)
    (ROOT / "var/evidence/v13-ci-project.json").write_text(json.dumps({"project": project_name()}), encoding="utf-8")
    compose("up", "-d", "--wait", "db")


def checks() -> None:
    from dotenv import dotenv_values

    project_name()
    environment = dict(os.environ, **{key: str(value) for key, value in dotenv_values(ROOT / ".env").items() if value is not None})
    python = str(ROOT / ".venv/bin/python")
    backend = ROOT / "backend"
    test_environment = dict(environment, S4_MIGRATION_DATABASE_URL=environment["S4_TEST_DATABASE_URL"])
    command(python, "-m", "alembic", "upgrade", "head", cwd=backend, env=test_environment)
    command(python, "-m", "pytest", "--cov=openkb_s4", "--cov-report=json:../var/evidence/backend-coverage.json",
            "--cov-report=xml:../var/evidence/coverage.xml", "--cov-fail-under=80", cwd=backend, env=environment)
    command(python, "-m", "ruff", "check", "src", "tests", cwd=backend)
    command(python, "-m", "mypy", cwd=backend)
    command(python, "scripts/export_contracts.py", env=environment)
    command(python, "scripts/extend_evidence_contracts.py", env=environment)
    command("git", "diff", "--exit-code", "--", "contracts")
    command("npm", "run", "generate-types", cwd=ROOT / "frontend")
    command("git", "diff", "--exit-code", "--", "frontend/src/generated/openapi.d.ts")
    for check in ("coverage", "lint", "build"):
        command("npm", "run", check, cwd=ROOT / "frontend")
    command("uv", "run", "--no-project", "--with", "jsonschema", "python", "scripts/check_contracts.py")
    command(python, "scripts/coverage_gate.py", "--base", os.environ.get("S4_COVERAGE_BASE", "892cf51"))
    command("gitleaks", "git", "--redact", "--no-banner", "--report-format", "json",
            "--report-path", "var/evidence/gitleaks-v13-ci.json")
    command(python, "scripts/dependency_audit.py")
    command("npm", "audit", "--registry=https://registry.npmjs.org", "--audit-level=high", cwd=ROOT / "frontend")
    with (ROOT / "var/evidence/frontend-sbom.cdx.json").open("w", encoding="utf-8") as output:
        subprocess.run(["npm", "sbom", "--sbom-format", "cyclonedx"], cwd=ROOT / "frontend", stdout=output, check=True)
    command("uv", "export", "--project", "backend", "--frozen", "--no-dev", "--no-emit-project",
            "--format", "cyclonedx1.5", "--output-file", "var/evidence/backend-sbom.cdx.json")
    command(python, "tests/e2e/prepare_v13.py", env=environment)
    browser_environment = {**environment,
                           **{key: str(value) for key, value in dotenv_values(ROOT / ".env.v13-e2e").items() if value is not None},
                           "S4_E2E_BROWSER": "chromium", "S4_E2E_URL": "http://localhost:5176"}
    processes = []
    logs = []
    try:
        for name, arguments, directory in (
            ("api", [python, "-m", "uvicorn", "openkb_s4.main:app", "--host", "127.0.0.1", "--port", "8004"], ROOT),
            ("worker", [python, "-m", "openkb_s4.worker"], ROOT),
            ("web", ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5176"], ROOT / "frontend"),
        ):
            log = (ROOT / f"var/evidence/v13-ci-{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            processes.append(subprocess.Popen(arguments, cwd=directory, env=browser_environment, stdout=log, stderr=subprocess.STDOUT))
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8004/api/s4/v2/health/ready", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise RuntimeError("v1.3 test services did not become ready")
        command("npx", "playwright", "install", "--with-deps", "chromium", cwd=ROOT / "tests/e2e")
        command("npx", "playwright", "test", "v13.spec.js", "--reporter=list", cwd=ROOT / "tests/e2e", env=browser_environment)
        container = f"{project_name()}-db-1"
        command(python, "scripts/backup_restore.py", "backup", "--env-file", ".env.v13-e2e", "--database", "s4_v13_e2e",
                "--data-dir", "var/v13-e2e", "--output", "backups/v13-ci-rehearsal", "--container", container, env=browser_environment)
        command(python, "scripts/backup_restore.py", "restore", "--env-file", ".env.v13-e2e",
                "--backup", "backups/v13-ci-rehearsal", "--container", container, env=browser_environment)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()


def cleanup() -> None:
    name = project_name()
    proof = ROOT / "var/evidence/v13-ci-project.json"
    if not proof.is_file() or json.loads(proof.read_text(encoding="utf-8"))["project"] != name:
        raise RuntimeError("This job did not create the matching isolated Compose project")
    compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["bootstrap", "checks", "cleanup"])
    mode = parser.parse_args().mode
    try:
        {"bootstrap": bootstrap, "checks": checks, "cleanup": cleanup}[mode]()
    except Exception as exc:  # noqa: BLE001 - never expose credential-bearing subprocess or DB error text.
        raise SystemExit(f"CI {mode} failed ({type(exc).__name__}); inspect retained verification artifacts.") from None
