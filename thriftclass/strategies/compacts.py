import struct
from typing import Type

INT_TIERS = [
    ("int8",   "b", -128,          127),
    ("uint8",  "B", 0,             255),
    ("int16",  "h", -32768,        32767),
    ("uint16", "H", 0,             65535),
    ("int32",  "i", -2147483648,   2147483647),
    ("uint32", "I", 0,             4294967295),
    ("int64",  "q", -9223372036854775808, 9223372036854775807),
]

SAFE_DEFAULTS = {
    int: ("int64", "q"),
    float: ("float64", "d"),
}


def classify_int_range(min_val: int, max_val: int):
    for name, fmt, lo, hi in INT_TIERS:
        if min_val >= lo and max_val <= hi:
            return name, fmt
    return "int64", "q"


def _check_overflow(value, fmt):
    for name, fmt_c, lo, hi in INT_TIERS:
        if fmt_c == fmt:
            if lo <= value <= hi:
                return
            raise OverflowError(
                f"Value {value} out of range for {name} ({lo}..{hi})"
            )


def _make_compact_descriptor(name: str, fmt: str, offset: int, check_overflow: bool):
    def getter(self):
        buf = object.__getattribute__(self, "__compact_buffer__")
        return struct.unpack_from(fmt, buf, offset)[0]

    if check_overflow:

        def setter(self, value):
            _check_overflow(value, fmt)
            buf = object.__getattribute__(self, "__compact_buffer__")
            struct.pack_into(fmt, buf, offset, value)
    else:

        def setter(self, value):
            buf = object.__getattribute__(self, "__compact_buffer__")
            struct.pack_into(fmt, buf, offset, value)

    return property(getter, setter, doc=f"Compact field '{name}' ({fmt})")


def _get_parent_buffer_size(cls):
    for ancestor in cls.__mro__[1:]:
        size = getattr(ancestor, "__compact_buffer_size__", None)
        if size is not None:
            return size
    return 0


def apply_compact_fields(cls: Type, annotations: dict, config, compact_overrides: dict | None = None) -> tuple[Type, dict]:
    compact_fields = {}
    for name, t in annotations.items():
        if not config.compact_ints and not config.compact_floats:
            continue
        if compact_overrides and name in compact_overrides:
            compact_fields[name] = compact_overrides[name]
        elif config.compact_ints and (t is int or t == "int"):
            compact_fields[name] = SAFE_DEFAULTS[int]
        elif config.compact_floats and (t is float or t == "float"):
            compact_fields[name] = SAFE_DEFAULTS[float]

    if not compact_fields:
        return cls, {}

    parent_total = _get_parent_buffer_size(cls)

    buf_offset = parent_total
    opts = {}
    descriptors_info = []

    for name, (type_name, fmt) in compact_fields.items():
        sz = struct.calcsize(fmt)
        opts[name] = f"{type_name} ({sz} bytes in buffer)"
        descriptors_info.append((name, fmt, buf_offset))
        buf_offset += sz

    total_buffer_size = buf_offset
    compact_names = set(compact_fields.keys())

    namespace = {}
    for key, val in vars(cls).items():
        if key in ("__dict__", "__weakref__"):
            continue
        if key in compact_names:
            continue
        if type(val).__name__ == "member_descriptor":
            continue
        namespace[key] = val

    old_slots = list(getattr(cls, "__slots__", ()))
    new_slots = [s for s in old_slots if s not in compact_names]
    if "__compact_buffer__" not in new_slots:
        new_slots.append("__compact_buffer__")
    namespace["__slots__"] = tuple(new_slots)

    check_overflow = getattr(config, "check_overflow", False)
    for name, fmt, offset in descriptors_info:
        namespace[name] = _make_compact_descriptor(name, fmt, offset, check_overflow)

    new_annotations = {k: v for k, v in annotations.items() if k not in compact_names}
    new_annotations["__compact_buffer__"] = bytes
    namespace["__annotations__"] = new_annotations

    original_init = namespace.get("__init__")

    new_cls = type(cls)(cls.__name__, cls.__bases__, namespace)
    new_cls.__module__ = cls.__module__
    new_cls.__qualname__ = cls.__qualname__
    new_cls.__compact_buffer_size__ = total_buffer_size

    parent_cls = cls.__bases__[0] if cls.__bases__ else object

    def compact_init(self, *args, **kwargs):
        try:
            buf = object.__getattribute__(self, "__compact_buffer__")
            if len(buf) < total_buffer_size:
                object.__setattr__(self, "__compact_buffer__", bytearray(total_buffer_size))
        except AttributeError:
            object.__setattr__(self, "__compact_buffer__", bytearray(total_buffer_size))
        if original_init:
            original_init(self, *args, **kwargs)
        elif parent_cls.__init__ is not object.__init__:
            parent_cls.__init__(self, *args)

    new_cls.__init__ = compact_init

    return new_cls, opts
