"""Utility helpers for thriftclass."""

from __future__ import annotations
import sys
import inspect
import dataclasses
from typing import Type, get_type_hints


def get_annotations(cls: Type) -> dict[str, type]:
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


def get_size(obj) -> int:
    """Get memory size of an object in bytes (shallow)."""
    return sys.getsizeof(obj)


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


def is_dataclass(cls: Type) -> bool:
    return dataclasses.is_dataclass(cls)


def is_pydantic(cls: Type) -> bool:
    try:
        from pydantic import BaseModel
        return issubclass(cls, BaseModel)
    except ImportError:
        return False


def copy_class_attributes(src, dst):
    """Copy methods and class attributes from src to dst, skipping dunder conflicts."""
    for name, val in vars(src).items():
        if name.startswith("__") and name.endswith("__"):
            continue
        try:
            setattr(dst, name, val)
        except (AttributeError, TypeError):
            pass
