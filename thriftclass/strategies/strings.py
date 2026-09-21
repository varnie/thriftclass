"""Intern exact strings while respecting inherited/custom attribute setters."""

import sys


def apply_string_interning(cls, str_fields):
    fields = frozenset(str_fields)
    original_setattr = cls.__setattr__

    def __setattr__(self, name, value):
        if name in fields and type(value) is str:
            value = sys.intern(value)
        original_setattr(self, name, value)

    cls.__setattr__ = __setattr__
    cls.__thrift_intern_fields__ = tuple(str_fields)
    return cls
