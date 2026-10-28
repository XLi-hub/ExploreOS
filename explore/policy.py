"""Frozen semantic ablations; execution, audit and budget machinery stay shared."""

DEFAULT = {"peer_critique": True, "direction_changes": True, "execution_failure_memory": True}


def normalize(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(DEFAULT) or any(type(v) is not bool for v in value.values()):
        raise ValueError("Exploration policy accepts only the documented boolean switches")
    return {**DEFAULT, **value}
