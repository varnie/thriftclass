"""Annotation discovery and approximate retained Python-object sizes."""

import dataclasses
import sys
import types
from collections import deque
from typing import ClassVar, get_origin, get_type_hints


def get_annotations(cls):
    hints = {}
    for base in reversed(cls.__mro__):
        hints.update(base.__dict__.get("__annotations__", {}))
    try:
        hints.update(get_type_hints(cls))
    except (NameError, TypeError):
        pass
    result = {}
    for name, value in hints.items():
        if get_origin(value) is ClassVar or isinstance(value, dataclasses.InitVar):
            continue
        if value is dataclasses.KW_ONLY:
            continue
        if isinstance(value, str):
            text = value.strip("'\"")
            if text.startswith(
                ("ClassVar[", "typing.ClassVar[", "InitVar[", "dataclasses.InitVar[")
            ):
                continue
            if text in ("KW_ONLY", "dataclasses.KW_ONLY"):
                continue
            value = {"int": int, "float": float, "str": str, "bool": bool}.get(text, value)
        result[name] = value
    return result


def deep_size(obj, seen=None):
    """Approximate retained bytes, visiting shared objects once and handling cycles.

    Includes builtin containers, instance dictionaries, and slots throughout the
    MRO. Excludes class/module/function graphs and external allocations.
    """
    seen = set() if seen is None else seen
    pending = [obj]
    size = 0
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        size += sys.getsizeof(value)
        if type(value) in (str, bytes, bytearray, int, float, bool, complex, type(None)):
            continue
        if isinstance(value, (type, types.ModuleType, types.FunctionType)):
            continue
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset, deque)):
            pending.extend(value)
        if type(value) in (dict, list, tuple, set, frozenset, deque):
            continue
        try:
            pending.append(object.__getattribute__(value, "__dict__"))
        except AttributeError:
            pass
        for base in type(value).__mro__:
            for descriptor in vars(base).values():
                if isinstance(descriptor, types.MemberDescriptorType):
                    try:
                        pending.append(descriptor.__get__(value, type(value)))
                    except AttributeError:
                        pass
    return size
