"""Keep tests away from the user's real netmed data directory.

Test modules that run CLI code which records command history or prepares
backends assign these as their module fixtures:

    from data_isolation import setUpModule, tearDownModule  # noqa: F401
"""

import os
import tempfile

_state = {}


def setUpModule():
    _state["directory"] = tempfile.TemporaryDirectory()
    _state["previous"] = os.environ.get("NETMED_DATA_DIR")
    os.environ["NETMED_DATA_DIR"] = _state["directory"].name


def tearDownModule():
    if _state.get("previous") is None:
        os.environ.pop("NETMED_DATA_DIR", None)
    else:
        os.environ["NETMED_DATA_DIR"] = _state["previous"]
    _state.pop("directory").cleanup()
