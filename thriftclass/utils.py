"""Utility helpers for thriftclass."""

from __future__ import annotations
import sys
from typing import get_type_hints


def get_annotations(cls: type) -> dict[str, type]:
    """
    Extract field annotations from a class, handling dataclasses,
    Pydantic models, and plain classes.
    """
    # Try get_type_hints first (resolves string annotations)
    try:
        hints = get_type_hints(cls)
        # Filter out ClassVar, private attrs
        hints = {
            k: v for k, v in hints.items()
            if not k.startswith("_")
        }
        if hints:
            return hints
    except Exception:
        pass

    # Fallback: raw __annotations__
    return {
        k: v for k, v in getattr(cls, "__annotations__", {}).items()
        if not k.startswith("_")
    }


def deep_size(obj, seen=None) -> int:
    """Recursively get total size of object and its contents."""
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)

    size = sys.getsizeof(obj)

    if hasattr(obj, "__dict__"):
        size += deep_size(obj.__dict__, seen)
    if hasattr(obj, "__slots__"):
        for slot in obj.__slots__:
            try:
                size += deep_size(getattr(obj, slot), seen)
            except AttributeError:
                pass

    return size


def find_ancestor_attr(cls, attr_name):
    """Walk MRO (excluding cls) and return first ancestor's attribute value."""
    for ancestor in cls.__mro__[1:]:
        val = getattr(ancestor, attr_name, None)
        if val is not None:
            return val
    return None
