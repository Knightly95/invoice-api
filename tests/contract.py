"""Checks responses against the frontend's OpenAPI contract (contract/schema.yml).

OpenAPI 3.0 schemas are almost JSON Schema: `$ref`s are resolved here and
`nullable: true` becomes "or null", then `jsonschema` does the checking.
"""

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

CONTRACT = Path(__file__).parent.parent / "contract" / "schema.yml"


@cache
def _spec() -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf8"))
    return spec


def _resolve(node: Any) -> Any:
    if isinstance(node, list):
        return [_resolve(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return _resolve(_spec()["components"]["schemas"][name])
    resolved = {key: _resolve(value) for key, value in node.items()}
    if resolved.pop("nullable", False):
        return {"anyOf": [resolved, {"type": "null"}]}
    return resolved


def response_schema(method: str, path: str, status: str = "200") -> dict[str, Any]:
    operation = _spec()["paths"][path][method.lower()]
    content = operation["responses"][status]["content"]["application/json"]
    schema: dict[str, Any] = _resolve(content["schema"])
    return schema


def assert_matches_contract(method: str, path: str, body: Any, status: str = "200") -> None:
    validator = Draft202012Validator(response_schema(method, path, status))
    errors = sorted(validator.iter_errors(body), key=lambda error: list(error.path))
    assert not errors, "\n".join(
        f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors[:5]
    )
