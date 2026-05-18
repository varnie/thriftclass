import struct

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


FMT_TO_RANGE = {fmt: (lo, hi) for _, fmt, lo, hi in INT_TIERS}
INT_FMT_TO_NAME = {fmt: name for name, fmt, _, _ in INT_TIERS}
FLOAT_FMT_TO_NAME = {"f": "float32", "d": "float64"}


def _check_overflow(value, fmt):
    result = FMT_TO_RANGE.get(fmt)
    if result is None:
        return
    lo, hi = result
    if not (lo <= value <= hi):
        name = INT_FMT_TO_NAME[fmt]
        raise OverflowError(
            f"Value {value} out of range for {name} ({lo}..{hi})"
        )


def _fmt_to_type_name(fmt: str) -> str:
    return INT_FMT_TO_NAME.get(fmt, FLOAT_FMT_TO_NAME.get(fmt, fmt))


def _make_compact_descriptor(name: str, fmt: str, offset: int, check_overflow: bool):
    st = struct.Struct(fmt)

    def getter(self):
        return st.unpack_from(object.__getattribute__(self, "__compact_buffer__"), offset)[0]

    def setter(self, value):
        if not isinstance(value, (int, float)):
            raise TypeError(
                f"Expected a numeric value for compact field '{name}', got {type(value).__name__}"
            )
        if check_overflow:
            _check_overflow(value, fmt)
        try:
            st.pack_into(object.__getattribute__(self, "__compact_buffer__"), offset, value)
        except struct.error:
            type_name = _fmt_to_type_name(fmt)
            raise OverflowError(
                f"Value {value} out of range for compact field '{name}' ({type_name})"
            )

    return property(getter, setter, doc=f"Compact field '{name}' ({fmt})")


def _get_parent_buffer_size(cls):
    from ..utils import find_ancestor_attr
    return find_ancestor_attr(cls, "__compact_buffer_size__") or 0


def apply_compact_fields(cls: type, annotations: dict, config,
                         compact_overrides: dict | None = None) -> tuple[type, dict]:
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
        st = struct.Struct(fmt)
        opts[name] = f"{type_name} ({st.size} bytes in buffer)"
        descriptors_info.append((name, fmt, buf_offset))
        buf_offset += st.size

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

    if getattr(config, "slots", True):
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
    all_compact_names = compact_names

    def compact_init(self, *args, **kwargs):
        try:
            buf = object.__getattribute__(self, "__compact_buffer__")
            if len(buf) < total_buffer_size:
                old = buf
                buf = bytearray(total_buffer_size)
                buf[:len(old)] = old
                object.__setattr__(self, "__compact_buffer__", buf)
        except AttributeError:
            object.__setattr__(self, "__compact_buffer__", bytearray(total_buffer_size))
        if original_init:
            original_init(self, *args, **kwargs)
        elif parent_cls.__init__ is not object.__init__:
            parent_cls.__init__(self, *args, **kwargs)
        for key, val in kwargs.items():
            if key in all_compact_names or original_init is None:
                setattr(self, key, val)

    new_cls.__init__ = compact_init

    return new_cls, opts
