"""Fallback for successful results that pinned Fire would display as object help."""

import inspect
import json
import types


def native_result(value, value_types):
    """Match Fire 0.7.1's result branches without inspecting printed help text."""
    return (
        value_types.HasCustomStr(value)
        or isinstance(value, (list, set, frozenset, types.GeneratorType, tuple))
        or inspect.isgeneratorfunction(value)
        or (isinstance(value, dict) and value_types.IsSimpleGroup(value))
        or isinstance(value, value_types.VALUE_TYPES)
    )


def result_serializer(save, *, fallback=None):
    from fire import value_types

    def serialize(value):
        # Navigating modules/classes/functions should still show their native help.
        # Explicit --help is handled by Fire before this hook is called.
        if (
            inspect.ismodule(value)
            or inspect.isclass(value)
            or inspect.isroutine(value)
        ):
            return value
        if native_result(value, value_types):
            return value
        reason = "No native text representation (__str__) or supported JSON exporter (to_json/tolist); saved as a Python object"
        for method in ("to_json", "tolist"):
            try:
                exporter = getattr(value, method, None)
                if not callable(exporter):
                    continue
                exported = exporter()
                if method == "to_json" and isinstance(
                    exported, (str, bytes, bytearray)
                ):
                    exported = json.loads(exported)
                # Validate and normalize actual JSON; no repr/str default converter.
                rendered = json.dumps(exported, ensure_ascii=False, allow_nan=False)
                return rendered
            except Exception as error:
                # Do not repeat the operation; preserve its original result below.
                reason = (
                    f"No native text representation (__str__); {method} export failed "
                    f"({type(error).__name__}); saved as a Python object"
                )
                continue
        if fallback is not None:
            return fallback(value, reason)
        return save(value, fallback_reason=reason)

    return serialize
