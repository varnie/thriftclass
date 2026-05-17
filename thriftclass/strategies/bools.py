"""
Strategy: Bool Packing

Multiple bool fields are packed into a single integer bitfield.
Access is transparent — fields still behave like normal bools.
"""

from __future__ import annotations
from typing import Type, TypeVar

T = TypeVar("T")


def _get_parent_bit_count(cls):
    for ancestor in cls.__mro__[1:]:
        bm = getattr(ancestor, "__thrift_bit_map__", None)
        if bm:
            return max(bm.values()) + 1
    return 0


def apply_bool_packing(cls: Type[T], bool_fields: list[str], annotations: dict) -> Type[T]:
    bit_offset = _get_parent_bit_count(cls)
    bit_map: dict[str, int] = {name: bit_offset + i for i, name in enumerate(bool_fields)}

    namespace: dict = {}
    for key, val in vars(cls).items():
        if key in ("__dict__", "__weakref__"):
            continue
        if key in bool_fields:
            continue
        if type(val).__name__ == "member_descriptor":
            continue
        namespace[key] = val

    old_slots = list(getattr(cls, "__slots__", ()))
    if old_slots:
        new_slots = [s for s in old_slots if s not in bool_fields]
        if "_bool_flags" not in [s for s in (getattr(b, '__slots__', ()) for b in cls.__mro__[1:]) for s in s]:
            if "_bool_flags" not in new_slots:
                new_slots.append("_bool_flags")
        namespace["__slots__"] = tuple(new_slots)

    for name, bit in bit_map.items():
        namespace[name] = _make_bool_property(name, bit)

    new_annotations = {k: v for k, v in annotations.items() if k not in bool_fields}
    new_annotations["_bool_flags"] = int
    namespace["__annotations__"] = new_annotations

    original_init = namespace.get("__init__")
    namespace["__init__"] = _make_init(original_init, bool_fields, bit_map, cls)

    new_cls = type(cls)(cls.__name__, cls.__bases__, namespace)
    new_cls.__module__ = cls.__module__
    new_cls.__qualname__ = cls.__qualname__
    new_cls.__thrift_bool_fields__ = bool_fields
    new_cls.__thrift_bit_map__ = bit_map
    return new_cls


def _make_bool_property(name: str, bit: int):
    mask = 1 << bit

    def getter(self):
        return bool(self._bool_flags & mask)

    def setter(self, value):
        if value:
            self._bool_flags |= mask
        else:
            self._bool_flags &= ~mask

    return property(getter, setter, doc=f"Bool field '{name}' (bit {bit})")


def _make_init(original_init, bool_fields: list[str], bit_map: dict[str, int], cls=None):
    parent_cls = cls.__bases__[0] if cls and cls.__bases__ else None
    has_bool_ancestor = any(
        getattr(b, "__thrift_bit_map__", None) for b in (cls.__mro__[1:] if cls else ())
    )

    def __init__(self, *args, **kwargs):
        if parent_cls and parent_cls.__init__ is not object.__init__:
            parent_cls.__init__(self, *args, **kwargs)
        if not has_bool_ancestor:
            object.__setattr__(self, "_bool_flags", 0)
        if original_init:
            original_init(self, *args, **kwargs)
        for key, val in kwargs.items():
            setattr(self, key, val)
    return __init__
