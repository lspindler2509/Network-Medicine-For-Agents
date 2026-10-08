"""Read small source metadata; delegate OpenAPI operation generation to Restish."""

from pathlib import Path
import yaml
import requests
from ..catalog import validate_url
from ..errors import UserError


def load_document(spec):
    if spec.startswith("https://"):
        validate_url(spec)
        response = requests.get(spec, timeout=30, allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise UserError("Spec redirects are disabled; configure the final URL")
        response.raise_for_status()
        document = yaml.safe_load(response.text)
    else:
        document = yaml.safe_load(Path(spec).read_text())
    if isinstance(document, dict) and document.get("swagger") == "2.0":
        raise UserError(
            "Swagger/OpenAPI 2 is not supported by Restish; use an OpenAPI 3 specification"
        )
    if not isinstance(document, dict) or not str(
        document.get("openapi", "")
    ).startswith(("3.0.", "3.1.")):
        raise UserError(
            "Expected OpenAPI 3.0.x or 3.1.x supported by the pinned Restish version"
        )
    return document


def documentation(spec):
    document = load_document(spec)
    return {
        "info": document.get("info", {}),
        "externalDocs": document.get("externalDocs", {}),
        "tags": document.get("tags", []),
    }


def discover(source, name, *, document=None):
    from ..runtime.restish import prepare

    if document is None:
        document = load_document(source["spec"])
    result = prepare(source, name, document)
    info = document.get("info", {})
    result["source_metadata"] = {
        "title": info.get("title", ""),
        "summary": info.get("summary", ""),
    }
    return result


def require_self_contained(document):
    """Release snapshots cannot resolve external reference documents."""
    if isinstance(document, dict):
        reference = document.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#")
        ):
            raise UserError(
                "Release API specifications must be self-contained; external $ref bundling is not implemented"
            )
        for item in document.values():
            require_self_contained(item)
    elif isinstance(document, list):
        for item in document:
            require_self_contained(item)
