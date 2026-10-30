"""Regenerate local API and review contracts directly from backend models.

No database connection, credential or production material is read by this command.
Run with the project's Python environment after changing API/schema definitions.
"""
from __future__ import annotations

import json
from pathlib import Path

from openkb_s4.domain.profiles import list_profiles
from openkb_s4.domain.v13 import ReviewV3, SourceEnvelope, Unit
from openkb_s4.main import create_app
from openkb_s4.schemas import ReviewV2

ROOT = Path(__file__).resolve().parents[1]


def write(name: str, value: object) -> None:
    (ROOT / 'contracts' / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )


def main() -> None:
    schema = ReviewV2.model_json_schema()
    schema.update({'$schema': 'https://json-schema.org/draft/2020-12/schema',
                   '$id': 'urn:openkb:s4-review:v2'})
    write('review-v2.schema.json', schema)
    openapi = create_app().openapi()
    components = openapi.setdefault('components', {}).setdefault('schemas', {})
    # Review payloads travel inside a phase envelope. Publish their concrete
    # model too so TypeScript clients need not recreate this business contract.
    api_review = ReviewV2.model_json_schema(ref_template='#/components/schemas/{model}')
    components.update(api_review.pop('$defs', {}))
    components['ReviewV2'] = api_review
    for name, model in (("ReviewV3", ReviewV3), ("SourceEnvelopeV2", SourceEnvelope)):
        published = model.model_json_schema(ref_template='#/components/schemas/{model}')
        components.update(published.pop('$defs', {}))
        components[name] = published
    write('openapi.json', openapi)
    # Human-readable baseline cards are derived from the registered strategies.
    write('profiles.json', list_profiles())
    for name, model in (("source-envelope", SourceEnvelope), ("unit", Unit), ("review", ReviewV3)):
        published_schema = model.model_json_schema()
        published_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        write(f"v13/{name}.schema.json", published_schema)
    print('Generated OpenAPI, legacy contracts and explicit v1.3 schemas.')


if __name__ == '__main__':
    main()
