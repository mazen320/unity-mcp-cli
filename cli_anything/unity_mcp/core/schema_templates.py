from __future__ import annotations

from typing import Any, Dict


def _placeholder_for_schema(schema: Dict[str, Any], include_optional: bool) -> Any:
    schema_type = schema.get("type")
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if schema_type == "string":
        return "<string>"
    if schema_type == "number":
        return 0.0
    if schema_type == "integer":
        return 0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [_placeholder_for_schema(item_schema, include_optional)]
        return []
    if schema_type == "object":
        return build_template_from_schema(schema, include_optional=include_optional)
    return "<value>"


def build_template_from_schema(
    schema: Dict[str, Any] | None,
    include_optional: bool = False,
) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}

    required = set(schema.get("required") or [])
    result: Dict[str, Any] = {}
    for name, property_schema in properties.items():
        if not include_optional and name not in required:
            continue
        if not isinstance(property_schema, dict):
            result[name] = "<value>"
            continue
        result[name] = _placeholder_for_schema(property_schema, include_optional)
    return result


def summarize_schema(schema: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {"required": [], "optional": [], "requiredTemplate": {}, "fullTemplate": {}}

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {"required": [], "optional": [], "requiredTemplate": {}, "fullTemplate": {}}

    required = list(schema.get("required") or [])
    optional = [name for name in properties if name not in required]
    return {
        "required": required,
        "optional": optional,
        "requiredTemplate": build_template_from_schema(schema, include_optional=False),
        "fullTemplate": build_template_from_schema(schema, include_optional=True),
    }
