"""Retry transient failures of build-time interface discovery.

Only read-only discovery requests (specifications, introspection, tool lists) use this;
user queries are never retried automatically.
"""

import time

import requests

ATTEMPTS = 3
DELAY = 5


def transient_http(error):
    """Connection problems, timeouts and HTTP 5xx responses."""
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(status, int) and status >= 500


def retry_transient(call, transient=transient_http, attempts=ATTEMPTS, delay=DELAY):
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            if attempt == attempts or not transient(error):
                raise
        time.sleep(delay * attempt)
