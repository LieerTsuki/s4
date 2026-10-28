"""Check changed executable lines against Python JSON and frontend LCOV reports.

Only runtime backend/src and frontend/src are measured; tests, CSS and type-only
declarations are verified separately. New untracked runtime files are included.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8')


def runtime_file(name: str) -> bool:
    path = Path(name)
    if not name.startswith(('backend/src/', 'frontend/src/')) or '/tests/' in name:
        return False
    return path.suffix in {'.py', '.ts', '.tsx'} and not name.endswith(('.d.ts', '/types.ts'))


def python_lines(path: Path) -> dict[str, dict[int, bool]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    files = {}
    for name, record in data['files'].items():
        file = Path(name)
        file = file if file.is_absolute() else ROOT / 'backend' / file
        relative = file.resolve().relative_to(ROOT).as_posix()
        files[relative] = {int(line): True for line in record['executed_lines']}
        files[relative].update({int(line): False for line in record['missing_lines']})
    return files


def frontend_lines(path: Path) -> dict[str, dict[int, bool]]:
    files: dict[str, dict[int, bool]] = {}
    current = None
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('SF:'):
            file = Path(line[3:])
            file = file if file.is_absolute() else ROOT / 'frontend' / file
            current = file.resolve().relative_to(ROOT).as_posix()
            files.setdefault(current, {})
        elif line.startswith('DA:') and current:
            number, count, *_ = line[3:].split(',')
            files[current][int(number)] = files[current].get(int(number), False) or int(count) > 0
        elif line == 'end_of_record':
            current = None
    return files


def changed_lines(base: str) -> dict[str, set[int]]:
    changes: dict[str, set[int]] = {}
    current = None
    for line in git('diff', '--no-ext-diff', '--no-renames', '--unified=0', base, '--', 'backend/src', 'frontend/src').splitlines():
        if line.startswith('+++ b/'):
            current = line[6:]
        elif current and line.startswith('@@'):
            match = re.search(r'\+(\d+)(?:,(\d+))? @@', line)
            if match:
                start, count = int(match[1]), int(match[2] or 1)
                changes.setdefault(current, set()).update(range(start, start + count))
    for name in git('ls-files', '--others', '--exclude-standard').splitlines():
        if runtime_file(name):
            changes[name] = set(range(1, len((ROOT / name).read_text(encoding='utf-8').splitlines()) + 1))
    return {name: lines for name, lines in changes.items() if runtime_file(name)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='00ef5c1')
    parser.add_argument('--backend', type=Path, default=ROOT / 'var/evidence/backend-coverage.json')
    parser.add_argument('--frontend', type=Path, default=ROOT / 'frontend/coverage/lcov.info')
    parser.add_argument('--minimum', type=float, default=80)
    parser.add_argument('--output', type=Path, default=ROOT / 'var/evidence/incremental-coverage.json')
    args = parser.parse_args()
    reports = {**python_lines(args.backend), **frontend_lines(args.frontend)}
    rows, missing = [], []
    for name, lines in sorted(changed_lines(args.base).items()):
        if name not in reports:
            source = (ROOT / name).read_text(encoding='utf-8').strip()
            if source and not (name.endswith('/__init__.py') and all(line.startswith('#') for line in source.splitlines())):
                missing.append(name)
            continue
        statements = sorted(lines & reports[name].keys())
        covered = sum(reports[name][line] for line in statements)
        rows.append({'file': name, 'changed_executable': len(statements), 'covered': covered,
                     'missing_lines': [line for line in statements if not reports[name][line]]})
    total = sum(row['changed_executable'] for row in rows)
    covered = sum(row['covered'] for row in rows)
    percent = 100 * covered / total if total else 100.0
    result = {'base': args.base, 'changed_executable': total, 'covered': covered, 'percent': percent,
              'minimum': args.minimum, 'files_without_coverage': missing, 'files': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}))
    if missing or percent < args.minimum:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
