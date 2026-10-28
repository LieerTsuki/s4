"""Build the local frozen-evidence schema and compatible report additions.

Version-one exports remain valid. Version-two reviews are validated with the
generated Pydantic schema; runtime checks additionally enforce object scope.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / 'contracts'
STRING = {'type': 'string', 'minLength': 1}
HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
DATE = {'type': 'string', 'format': 'date-time'}


def save(name: str, value: Any) -> None:
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def record(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {'type': 'object', 'additionalProperties': False,
            'required': required if required is not None else list(properties), 'properties': properties}


def rows(item: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'array', 'items': item}


def main() -> None:
    nullable_id = {'type': ['string', 'null']}
    assignment = record({'id': STRING, 'unit_id': STRING, 'batch_id': STRING, 'user_id': STRING,
                         'seat': {'enum': ['A', 'B']}, 'active': {'type': 'boolean'},
                         'content_revision': STRING, 'unit_revision_id': nullable_id,
                         'gold_revision_id': nullable_id, 'replacement_id': nullable_id})
    submission = record({'id': STRING, 'assignment_id': STRING, 'phase': {'enum': ['BLIND', 'REVIEW']},
                         'payload': {'type': 'object'}, 'payload_hash': HASH, 'created_at': DATE})
    agreement = record({'id': STRING, 'batch_id': STRING, 'input_hash': HASH, 'vectors': {'type': 'object'},
                        'result': {'type': 'object'}, 'profile_snapshot': {'type': ['object', 'null']},
                        'profile_hash': {'anyOf': [HASH, {'type': 'null'}]},
                        'manual_version': {'anyOf': [STRING, {'type': 'null'}]},
                        'review_version': {'enum': ['openkb.s4-review.v1', 'openkb.s4-review.v2']},
                        'legacy': {'type': 'boolean'}})
    agreement['if'] = {'properties': {'review_version': {'const': 'openkb.s4-review.v2'}}}
    agreement['then'] = {'properties': {'profile_snapshot': {'type': 'object'}, 'profile_hash': HASH, 'manual_version': STRING, 'legacy': {'const': False}}}
    validation = record({'id': STRING, 'batch_id': STRING, 'unit_id': STRING, 'content_hash': HASH,
                         'profile_hash': HASH, 'status': {'enum': ['PASS', 'FAIL', 'PENDING', 'NOT_REQUIRED']},
                         'change_kind': {'enum': ['UNCHANGED', 'LOCATOR_ONLY', 'SUBSTANTIVE']},
                         'validation_revision': STRING, 'verifier_id': nullable_id, 'editor_id': nullable_id,
                         'evidence': {'type': 'object'}, 'evidence_hash': HASH, 'reason': STRING,
                         'created_at': DATE})
    calibration = record({'id': STRING, 'batch_id': STRING, 'original_agreement': {'type': 'object'},
                          'case_refs': rows(STRING), 'meeting_at': DATE, 'participant_ids': rows(STRING),
                          'decisions': STRING, 'manual_version': STRING, 'training_refs': rows(STRING), 'reason': STRING})
    arbitration = json.loads((ROOT / 'arbitration-record.schema.json').read_text(encoding='utf-8'))
    arbitration['properties'].update({'confirmation_reason': STRING, 'confirmed_at': {'type': ['string', 'null'], 'format': 'date-time'}, 'created_at': DATE})
    save('arbitration-record.schema.json', arbitration)
    bundle = record({'contract_version': {'const': 'openkb.s4-evidence.v1'}, 'audit_cutoff_at': DATE, 'handoff_id': STRING,
                      'snapshot_hash': HASH, 'source_import_id': STRING, 'source_hash': HASH,
                      'raw_source': {'type': 'object'}, 'assignments': rows(assignment),
                      'submissions': rows(submission), 'agreements': rows(agreement),
                      'validations': rows(validation), 'calibrations': rows(calibration),
                      'final_decisions': rows(record({'id': STRING, 'batch_id': STRING, 'unit_id': STRING,
                                                       'final_gold': {'type': 'object'}, 'reason': STRING,
                                                       'actor_id': STRING, 'created_at': DATE})),
                      'arbitrations': rows({key: value for key, value in arbitration.items() if not key.startswith('$')}),
                      'audit_events': rows(record({'id': STRING, 'actor_id': nullable_id, 'action': STRING,
                                                   'object_id': nullable_id, 'request_id': STRING,
                                                   'details': {'type': 'object'}, 'created_at': DATE}))})
    # Embedded arbitration references must resolve at this document's root.
    bundle['$defs'] = deepcopy(arbitration.get('$defs', {}))
    bundle.update({'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:openkb:s4-evidence:v1'})
    save('evidence-bundle.schema.json', bundle)
    report = json.loads((ROOT / 's4-report.schema.json').read_text(encoding='utf-8'))
    report['properties']['evidence_bundle'] = {key: value for key, value in bundle.items() if key not in {'$schema', '$id', '$defs'}}
    report['properties']['evidence_sha256'] = HASH
    report['dependentRequired'] = {'evidence_bundle': ['evidence_sha256'], 'evidence_sha256': ['evidence_bundle']}
    report['$defs'] = deepcopy(bundle['$defs'])
    save('s4-report.schema.json', report)
    review = json.loads((ROOT / 'review-v2.schema.json').read_text(encoding='utf-8'))
    iaa = json.loads((ROOT / 'iaa-record.schema.json').read_text(encoding='utf-8'))
    # Legacy grades retain their archived shape. A v2 marker opts into the strict schema.
    iaa['$defs'] = deepcopy(review.get('$defs', {}))
    review_body = {key: value for key, value in review.items() if key not in {'$schema', '$id', '$defs'}}
    for field in ('grades_a', 'grades_b'):
        iaa['properties'][field] = {'type': 'object', 'if': {'required': ['review_version'], 'properties': {'review_version': {'const': 'openkb.s4-review.v2'}}}, 'then': review_body}
    save('iaa-record.schema.json', iaa)
    imported = json.loads((ROOT / 'import.schema.json').read_text(encoding='utf-8'))
    unit_result = imported['$defs']['unit_result']
    point = record({'point_key': {'type': 'string', 'pattern': '^P[0-9]{3,}$'},
                    'point_sha256': HASH, 'content_sha256': HASH,
                    'reverse_validation': record({'status': {'const': 'PASS'}, 'model': STRING,
                                                   'version': STRING, 'coverage': {'const': 1, 'type': 'integer'}}),
                    'nli': deepcopy(unit_result['properties']['nli']),
                    'fallback': deepcopy(unit_result['properties']['fallback'])},
                   ['point_key', 'point_sha256', 'content_sha256', 'reverse_validation', 'nli'])
    point['allOf'] = deepcopy(unit_result['allOf'])
    unit_result['properties']['point_results'] = {**rows(point), 'minItems': 1}
    point_required = {'if': {'required': ['unit_id'], 'properties': {'unit_id': {'pattern': '^QA-D[12357]-'}}},
                      'then': {'required': ['point_results']}}
    if point_required not in unit_result['allOf']:
        unit_result['allOf'].append(point_required)
    save('import.schema.json', imported)
    fixture_path = ROOT / 'examples/synthetic-formal-contract-test.json'
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
    units = {unit['unit_id']: unit for unit in fixture['units']}
    def digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    for result in fixture['s3_report']['unit_results']:
        result['point_results'] = [
            {'point_key': f'P{index+1:03d}', 'point_sha256': digest(text),
             'content_sha256': digest(units[result['unit_id']]),
             'reverse_validation': {**result['reverse_validation'], 'version': fixture['s3_report']['validator_version'], 'coverage': 1},
             'nli': deepcopy(result['nli'])}
            for index, text in enumerate(units[result['unit_id']].get('gold', {}).get('answer_points', []))
        ]
    save('examples/synthetic-formal-contract-test.json', fixture)
    demo = json.loads((ROOT / 'examples/demo-import.json').read_text(encoding='utf-8'))['units'][0]
    doc_id = demo['gold']['gold_doc_ids'][0]
    save('examples/review-v2.json', {
        'review_version': 'openkb.s4-review.v2',
        'point_labels': {'P001': 'correct', 'P002': 'partial', 'P003': 'wrong'},
        'point_reasons': {'P001': '原文规定五个工作日。', 'P002': '表单正确，邮件渠道不符。', 'P003': '全文未支持不留凭证的说法。'},
        'point_evidence': {'P001': [{'doc_id': doc_id, 'span': '办理期限'}], 'P002': [{'doc_id': doc_id, 'span': '提交渠道'}], 'P003': []},
        'point_search_scope': {'P003': [doc_id]}, 'evidence_labels': {doc_id: 2},
        'evidence_reasons': {doc_id: '同一授权原文包含期限、渠道和凭证要求。'},
        'answerable': 'answerable', 'answerable_reason': '授权原文足以回答本题。',
        'reason': '仅为合成协议样例。', 'suggested_points': [], 'evidence_changes': []})
    print('Frozen evidence contracts extended; legacy exports remain readable.')


if __name__ == '__main__':
    main()
