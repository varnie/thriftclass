"""
Strategy: String Interning

String fields are automatically interned via sys.intern().
When many objects share the same string values (e.g. status="active",
role="admin"), they point to the same object in memory instead of
each holding their own copy.

Patches __init__ and __setattr__ IN-PLACE to avoid __slots__ conflicts.
"""

from __future__ import annotations
import sys
from typing import TypeVar

T = TypeVar("T")


def apply_string_interning(cls: type[T], str_fields: list[str]) -> type[T]:
    """
    Patches __init__ and __setattr__ on the class in-place to intern strings.
    Does not recreate the class — avoids __slots__ conflicts.
    """
    original_init = cls.__dict__.get("__init__")
    original_setattr = cls.__dict__.get("__setattr__")

    cls.__init__ = _make_init(original_init, str_fields, cls)
    cls.__setattr__ = _make_setattr(original_setattr, str_fields)
    cls.__thrift_intern_fields__ = str_fields  # type: ignore
    return cls


def _make_init(original_init, str_fields: list[str], cls=None):
    fields_set = set(str_fields)
    parent_cls = cls.__bases__[0] if cls and cls.__bases__ else None

    def __init__(self, *args, **kwargs):
        for key in list(kwargs.keys()):
            if key in fields_set and isinstance(kwargs[key], str):
                kwargs[key] = sys.intern(kwargs[key])

        if original_init:
            original_init(self, *args, **kwargs)
        else:
            for key, val in kwargs.items():
                object.__setattr__(self, key, val)
            if parent_cls and parent_cls.__init__ is not object.__init__:
                parent_cls.__init__(self, *args, **kwargs)

        for fname in str_fields:
            try:
                val = object.__getattribute__(self, fname)
                if isinstance(val, str):
                    object.__setattr__(self, fname, sys.intern(val))
            except AttributeError:
                pass

    return __init__


def _make_setattr(original_setattr, str_fields: list[str]):
    fields_set = set(str_fields)

    def __setattr__(self, name, value):
        if name in fields_set and isinstance(value, str):
            value = sys.intern(value)
        if original_setattr:
            original_setattr(self, name, value)
        else:
            object.__setattr__(self, name, value)

    return __setattr__
