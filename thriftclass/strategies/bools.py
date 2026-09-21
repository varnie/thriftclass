"""Properties backed by a shared integer bitfield."""


def make_bool_property(name, bit):
    mask = 1 << bit
    inverse = ~mask

    def getter(self):
        return bool(self._bool_flags & mask)

    def setter(self, value):
        flags = self._bool_flags
        object.__setattr__(self, "_bool_flags", flags | mask if value else flags & inverse)

    return property(getter, setter, doc=f"Bool field '{name}' (bit {bit})")
