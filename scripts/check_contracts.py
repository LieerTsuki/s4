"""Validate local JSON Schemas and optional real synthetic export snapshots.

Run with: uv run --no-project --with jsonschema python scripts/check_contracts.py
"""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exports', type=Path, help='Controlled export root containing handoff directories.')
    args = parser.parse_args()
    validators = {}
    for path in (ROOT / 'contracts').rglob('*.schema.json'):
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        validators[path.name] = Draft202012Validator(schema, format_checker=FormatChecker())
    v13_root = ROOT / 'contracts' / 'v13' / 'examples'
    current_source = json.loads((v13_root / 'demo-import.json').read_text(encoding='utf-8'))
    current_review = json.loads((v13_root / 'review-needs-revision.json').read_text(encoding='utf-8'))
    validators['source-envelope.schema.json'].validate(current_source)
    validators['review.schema.json'].validate(current_review)
    for name in ('demo-import.json', 'synthetic-formal-contract-test.json'):
        validators['import.schema.json'].validate(json.loads((ROOT / 'contracts/examples' / name).read_text(encoding='utf-8')))
    formal = json.loads((ROOT / 'contracts/examples/synthetic-formal-contract-test.json').read_text(encoding='utf-8'))
    del formal['s3_report']['unit_results'][0]['point_results']
    if validators['import.schema.json'].is_valid(formal):
        raise ValueError('Formal QA contract accepted missing per-point S3 evidence.')
    review = json.loads((ROOT / 'contracts/examples/review-v2.json').read_text(encoding='utf-8'))
    validator = validators['review-v2.schema.json']
    validator.validate(review)
    for invalid in (
        {**review, 'evidence_labels': {'doc': 3}},
        {**review, 'point_reasons': {'P001': ''}},
        {**review, 'suggested_points': True},
        {**review, 'unexpected': 'cannot silently add fields'},
    ):
        try:
            validator.validate(invalid)
        except ValidationError:
            continue
        raise ValueError('REVIEW v2 schema accepted a negative contract fixture.')
    files = {'units_for_s5.jsonl': 'export-unit.schema.json', 'labeled.jsonl': 'export-unit.schema.json',
             'iaa_records.jsonl': 'iaa-record.schema.json', 'arbitration_log.jsonl': 'arbitration-record.schema.json',
             's4_report.json': 's4-report.schema.json', 's4_handoff_manifest.json': 'handoff-manifest.schema.json'}
    snapshots = 0
    if args.exports:
        for manifest in args.exports.glob('*/s4_handoff_manifest.json'):
            current_manifest = json.loads(manifest.read_text(encoding='utf-8'))
            if current_manifest.get('contract_version') == 'openkb.s4-s5.v2':
                from openkb_s4.services.handoffs_v13 import verify_package
                verify_package(manifest.parent, current_manifest)
                snapshots += 1
                continue
            for filename, schema_name in files.items():
                content = (manifest.parent / filename).read_text(encoding='utf-8')
                rows = [json.loads(row) for row in content.splitlines()] if filename.endswith('.jsonl') else [json.loads(content)]
                for row in rows:
                    validators[schema_name].validate(row)
                    if filename == 's4_report.json' and 'evidence_bundle' in row:
                        import hashlib
                        canonical = json.dumps(row['evidence_bundle'], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
                        if hashlib.sha256(canonical).hexdigest() != row['evidence_sha256']:
                            raise ValueError('Evidence bundle digest differs from frozen report.')
                        invalid = deepcopy(row)
                        invalid['evidence_bundle']['contract_version'] = 'unrecognized'
                        if validators[schema_name].is_valid(invalid):
                            raise ValueError('Report contract did not validate embedded evidence version.')
                    if filename == 'labeled.jsonl' and not {'annotation_batch_id', 'round'} <= row.keys():
                        raise ValueError('Labeled row lacks frozen batch identity.')
            snapshots += 1
    print(f'{len(validators)} schemas valid; 3 synthetic examples and 4 negative REVIEW contracts valid; {snapshots} export snapshots valid.')


if __name__ == '__main__':
    main()
