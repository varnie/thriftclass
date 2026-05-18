"""
MemoryReport — human-readable summary of thrift optimizations.
"""

from __future__ import annotations
from dataclasses import dataclass, field


STRATEGY_LABELS = {
    "slots":           ("__slots__",           "eliminates per-object __dict__"),
    "bool_packing":    ("bool → bitfield",     "packs bool fields into one int"),
    "string_interning":("str interning",       "interned strings share memory"),
    "compact_ints":    ("compact ints/floats", "stored in bytearray buffer"),
    "adaptive":        ("adaptive monitor",    "learns from real data to suggest types"),
}


@dataclass
class MemoryReport:
    class_name: str
    strategies: list[str]
    original_size: int
    optimized_size: int
    field_info: dict[str, dict] = field(default_factory=dict)

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.optimized_size)

    @property
    def saved_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return round(100 * self.saved_bytes / self.original_size, 1)

    def show(self) -> None:
        """Print a formatted report to stdout."""
        print(self._render())

    def _render(self) -> str:
        width = 58
        sep = "─" * width
        lines = []

        def pad(s):
            return f"{s:<{width}.{width}}"

        lines.append(f"┌{sep}┐")
        lines.append(f"│{pad(f'  thriftclass — {self.class_name}')}│")
        lines.append(f"├{sep}┤")

        if self.original_size and self.optimized_size:
            lines.append(f"│{pad('  Memory per instance:')}│")
            lines.append(f"│{pad(f'    Before : {self.original_size:>5} bytes')}│")
            lines.append(f"│{pad(f'    After  : {self.optimized_size:>5} bytes')}│")
            if self.saved_bytes:
                saved_str = f'{self.saved_bytes:>5} bytes  ({self.saved_percent}%)'
                lines.append(f"│{pad(f'    Saved  : {saved_str}')}│")
            else:
                lines.append(f"│{pad('  (size estimation requires dummy-constructable class)')}│")
        else:
            lines.append(f"│{pad('  (size estimation not available for this class type)')}│")

        lines.append(f"├{sep}┤")

        lines.append(f"│{pad('  Optimizations applied:')}│")
        if self.strategies:
            for s in self.strategies:
                label, desc = STRATEGY_LABELS.get(s, (s, ""))
                lines.append(f"│{pad(f'    ✓  {label:<18}  {desc}')}│")
        else:
            lines.append(f"│{pad('    (none)')}│")

        if "adaptive" in self.strategies:
            lines.append(f"├{sep}┤")
            msg = f'  ▶  Call {self.class_name}.optimize() to apply recommendations'
            lines.append(f"│{pad(msg)}│")

        if self.field_info:
            has_any = any(v.get("optimizations") for v in self.field_info.values())
            if has_any:
                lines.append(f"├{sep}┤")
                lines.append(f"│{pad('  Fields:')}│")
                for fname, info in self.field_info.items():
                    opts = info.get("optimizations", [])
                    if opts:
                        opt_str = ", ".join(opts)
                        lines.append(f"│{pad(f'    {fname:<14}  → {opt_str}')}│")

        lines.append(f"└{sep}┘")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"MemoryReport({self.class_name!r}, "
            f"saved={self.saved_percent}%, "
            f"strategies={self.strategies})"
        )


