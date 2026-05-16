"""
Strategy: __slots__

Replaces __dict__ with __slots__, saving ~40-50% per instance
by eliminating the per-object dictionary.
"""

from __future__ import annotations
import dataclasses
from typing import Type, TypeVar

T = TypeVar("T")


def apply_slots(cls: Type[T], annotations: dict) -> Type[T]:
    """
    Rebuild the class with __slots__ defined.
    Handles plain classes, dataclasses.
    """
    if "__slots__" in cls.__dict__:
        # Already has slots — nothing to do
        return cls

    if dataclasses.is_dataclass(cls):
        return _slots_for_dataclass(cls, annotations)

    return _slots_for_plain_class(cls, annotations)


def _slots_for_plain_class(cls: Type[T], annotations: dict) -> Type[T]:
    """Rebuild a plain class with __slots__."""
    slot_names = list(annotations.keys())

    # Collect everything from original class except __dict__ and __weakref__
    namespace = {}
    for key, val in vars(cls).items():
        if key in ("__dict__", "__weakref__"):
            continue
        namespace[key] = val

    namespace["__slots__"] = tuple(slot_names)
    # Remove annotations that become slots (avoid conflict)
    namespace.pop("__annotations__", None)
    namespace["__annotations__"] = annotations

    new_cls = type(cls)(cls.__name__, cls.__bases__, namespace)
    new_cls.__module__ = cls.__module__
    new_cls.__qualname__ = cls.__qualname__
    return new_cls


def _slots_for_dataclass(cls: Type[T], annotations: dict) -> Type[T]:
    import sys

    if sys.version_info >= (3, 10):
        raw_fields = {f.name: f for f in dataclasses.fields(cls)}

        field_defs = {}
        for name, f in raw_fields.items():
            if f.default is not dataclasses.MISSING:
                field_defs[name] = dataclasses.field(default=f.default)
            elif f.default_factory is not dataclasses.MISSING:
                field_defs[name] = dataclasses.field(default_factory=f.default_factory)
            else:
                field_defs[name] = dataclasses.field()

        base_ns = {"__annotations__": annotations, **field_defs}
        new_cls = type(cls.__name__, cls.__bases__, base_ns)
        new_cls = dataclasses.dataclass(new_cls, slots=True)

        for key, val in vars(cls).items():
            if key.startswith("__") and key.endswith("__"):
                continue
            if key in raw_fields:
                continue
            try:
                setattr(new_cls, key, val)
            except (AttributeError, TypeError):
                pass

        new_cls.__module__ = cls.__module__
        new_cls.__qualname__ = cls.__qualname__
        return new_cls
    else:
        return _slots_for_plain_class(cls, annotations)
        