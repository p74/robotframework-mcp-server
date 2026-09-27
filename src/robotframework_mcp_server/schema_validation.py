from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SchemaValidationLibrary:
    """Minimal schema validation helpers for generated Robot Framework API suites."""

    def response_should_match_schema_file(self, payload: Any, schema_path: str) -> None:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.response_should_match_schema(payload, schema)

    def response_should_match_schema(self, payload: Any, schema: Any) -> None:
        parsed_payload = json.loads(payload) if isinstance(payload, str) else payload
        self._validate(parsed_payload, schema, path="$")

    def _validate(self, payload: Any, schema: Any, path: str) -> None:
        if not isinstance(schema, dict):
            return
        schema_type = schema.get("type")
        schema_types = schema_type if isinstance(schema_type, list) else [schema_type] if schema_type else []
        if payload is None and (schema.get("nullable") or "null" in schema_types):
            return
        if "oneOf" in schema and not any(self._matches(payload, option, path) for option in schema["oneOf"]):
            raise AssertionError(f"{path} did not satisfy any oneOf schema option")
        if "anyOf" in schema and not any(self._matches(payload, option, path) for option in schema["anyOf"]):
            raise AssertionError(f"{path} did not satisfy any anyOf schema option")
        if "allOf" in schema:
            for option in schema["allOf"]:
                self._validate(payload, option, path)
        if "enum" in schema and payload not in schema["enum"]:
            raise AssertionError(f"{path} expected one of {schema['enum']!r} but got {payload!r}")

        if isinstance(schema_type, list):
            non_null_types = [item for item in schema_type if item != "null"]
            schema_type = non_null_types[0] if non_null_types else None

        if schema_type == "object" or schema.get("properties") or schema.get("required"):
            if not isinstance(payload, dict):
                raise AssertionError(f"{path} expected object but got {type(payload).__name__}")
            for required_name in schema.get("required", []):
                if required_name not in payload:
                    raise AssertionError(f"{path}.{required_name} is required")
            for name, child_schema in schema.get("properties", {}).items():
                if name in payload:
                    self._validate(payload[name], child_schema, f"{path}.{name}")
            return

        if schema_type == "array":
            if not isinstance(payload, list):
                raise AssertionError(f"{path} expected array but got {type(payload).__name__}")
            item_schema = schema.get("items", {})
            for index, item in enumerate(payload):
                self._validate(item, item_schema, f"{path}[{index}]")
            return

        if schema_type == "string" and not isinstance(payload, str):
            raise AssertionError(f"{path} expected string but got {type(payload).__name__}")
        if schema_type == "integer" and (isinstance(payload, bool) or not isinstance(payload, int)):
            raise AssertionError(f"{path} expected integer but got {type(payload).__name__}")
        if schema_type == "number" and (isinstance(payload, bool) or not isinstance(payload, (int, float))):
            raise AssertionError(f"{path} expected number but got {type(payload).__name__}")
        if schema_type == "boolean" and not isinstance(payload, bool):
            raise AssertionError(f"{path} expected boolean but got {type(payload).__name__}")

    def _matches(self, payload: Any, schema: Any, path: str) -> bool:
        try:
            self._validate(payload, schema, path)
        except AssertionError:
            return False
        return True
