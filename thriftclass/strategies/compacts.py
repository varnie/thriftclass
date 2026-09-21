import operator
import struct

INT_TIERS = [
    ("int8", "b", -128, 127),
    ("uint8", "B", 0, 255),
    ("int16", "h", -32768, 32767),
    ("uint16", "H", 0, 65535),
    ("int32", "i", -2147483648, 2147483647),
    ("uint32", "I", 0, 4294967295),
    ("int64", "q", -9223372036854775808, 9223372036854775807),
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


def _fmt_to_type_name(fmt: str) -> str:
    return INT_FMT_TO_NAME.get(fmt, FLOAT_FMT_TO_NAME.get(fmt, fmt))


def _make_compact_descriptor(name: str, fmt: str, offset: int):
    st = struct.Struct("=" + fmt)
    integer = fmt in FMT_TO_RANGE
    limits = FMT_TO_RANGE.get(fmt)

    def getter(self):
        return st.unpack_from(self.__compact_buffer__, offset)[0]

    def setter(self, value):
        if integer:
            # Match integer storage semantics without misreporting floats as overflow.
            try:
                value = operator.index(value)
            except TypeError:
                raise TypeError(f"Expected an integer for compact field '{name}'") from None
        elif not isinstance(value, (int, float)):
            raise TypeError(f"Expected a number for compact field '{name}'")
        if integer:
            lo, hi = limits
            if not lo <= value <= hi:
                raise OverflowError(f"Value {value} out of range for compact field '{name}'")
        else:
            value = float(value)
            if fmt == "f":
                # Validate narrowing before pack_into can alter existing bytes.
                st.pack(value)
        try:
            st.pack_into(self.__compact_buffer__, offset, value)
        except struct.error as exc:
            type_name = _fmt_to_type_name(fmt)
            raise OverflowError(
                f"Value {value} out of range for compact field '{name}' ({type_name})"
            ) from exc

    return property(getter, setter, doc=f"Compact field '{name}' ({fmt})")
