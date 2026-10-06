"""Discover operations deterministically from OpenAPI 3 and Swagger 2."""
import copy
import re
from pathlib import Path
import yaml
import requests
from ..catalog import validate_url


def resolve(value, document, seen=()):
    if isinstance(value, list):
        return [resolve(v, document, seen) for v in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("External schema references are not supported yet")
        if ref in seen:
            return {"$ref": ref}  # Preserve recursive schema documentation.
        target = document
        for segment in ref[2:].split("/"):
            target = target[segment.replace("~1", "/").replace("~0", "~")]
        target = copy.deepcopy(target)
        target.update({k: v for k, v in value.items() if k != "$ref"})
        return resolve(target, document, seen + (ref,))
    return {k: resolve(v, document, seen) for k, v in value.items()}


def discover(spec):
    if spec.startswith("https://"):
        validate_url(spec)
        response = requests.get(spec, timeout=30, allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise ValueError("Spec redirects are disabled; configure the final URL")
        response.raise_for_status()
        document = yaml.safe_load(response.text)
    else:
        document = yaml.safe_load(Path(spec).read_text())
    if not isinstance(document, dict) or not (str(document.get("openapi", "")).startswith("3.") or document.get("swagger") == "2.0"):
        raise ValueError("Expected OpenAPI 3.x or Swagger 2.0")
    operations = {}
    for path, raw in document.get("paths", {}).items():
        item = resolve(raw, document)
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise ValueError("Invalid operation path")
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            name = operation.get("operationId") or re.sub(r"[^a-zA-Z0-9]+", "_", method + "_" + path).strip("_")
            if name in operations:
                raise ValueError(f"Duplicate operationId: {name}")
            merged = {(p['in'], p['name']): p for p in item.get('parameters', [])}
            merged.update({(p['in'], p['name']): p for p in operation.get('parameters', [])})
            operations[name] = {
                "method": method.upper(), "path": path,
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                "parameters": list(merged.values()),
                "requestBody": operation.get("requestBody"),
                "security": operation.get("security", document.get("security", [])),
            }
    return operations
