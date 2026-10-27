"""Validate local JSON Schemas and optional real synthetic export snapshots.

Run with: uv run --no-project --with jsonschema python scripts/check_contracts.py
"""
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exports', type=Path, help='Controlled export root containing handoff directories.')
    args = parser.parse_args()
    validators = {}
    for path in (ROOT / 'contracts').glob('*.schema.json'):
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        validators[path.name] = Draft202012Validator(schema, format_checker=FormatChecker())
    for name in ('demo-import.json', 'synthetic-formal-contract-test.json'):
        validators['import.schema.json'].validate(json.loads((ROOT / 'contracts/examples' / name).read_text(encoding='utf-8')))
    files = {'units_for_s5.jsonl': 'export-unit.schema.json', 'labeled.jsonl': 'export-unit.schema.json',
             'iaa_records.jsonl': 'iaa-record.schema.json', 'arbitration_log.jsonl': 'arbitration-record.schema.json',
             's4_report.json': 's4-report.schema.json', 's4_handoff_manifest.json': 'handoff-manifest.schema.json'}
    snapshots = 0
    if args.exports:
        for manifest in args.exports.glob('*/s4_handoff_manifest.json'):
            for filename, schema_name in files.items():
                content = (manifest.parent / filename).read_text(encoding='utf-8')
                rows = [json.loads(row) for row in content.splitlines()] if filename.endswith('.jsonl') else [json.loads(content)]
                for row in rows:
                    validators[schema_name].validate(row)
                    if filename == 'labeled.jsonl' and not {'annotation_batch_id', 'round'} <= row.keys():
                        raise ValueError('Labeled row lacks frozen batch identity.')
            snapshots += 1
    print(f'{len(validators)} schemas valid; 2 synthetic input examples valid; {snapshots} export snapshots valid.')


if __name__ == '__main__':
    main()
