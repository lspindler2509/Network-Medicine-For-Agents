"""Standard GraphQL-over-HTTP envelope, without provider-specific behavior."""

import requests
from ..errors import UserError


def post(source, query, variables=None, operation_name=None):
    body = {"query": query}
    if variables is not None:
        body["variables"] = variables
    if operation_name is not None:
        body["operationName"] = operation_name
    response = requests.post(
        source["endpoint"],
        json=body,
        headers={"Accept": "application/graphql-response+json, application/json"},
        timeout=source.get("timeout", 60),
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise UserError("GraphQL endpoint redirected; update its configured HTTPS URL")
    try:
        payload = response.json()
    except ValueError as error:
        raise UserError(
            f"GraphQL endpoint returned non-JSON output (HTTP {response.status_code})"
        ) from error
    if not isinstance(payload, dict) or not (
        "data" in payload or isinstance(payload.get("errors"), list)
    ):
        raise UserError("GraphQL endpoint returned an invalid response envelope")
    if "errors" in payload and not isinstance(payload["errors"], list):
        raise UserError("GraphQL errors must be an array")
    if (
        "data" in payload
        and payload["data"] is not None
        and not isinstance(payload["data"], dict)
    ):
        raise UserError("GraphQL data must be an object or null")
    return payload, response.status_code
