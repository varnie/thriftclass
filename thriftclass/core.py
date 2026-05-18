"""
Core decorator and configuration for thriftclass.
"""

from __future__ import annotations

import sys
import dataclasses
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar, overload

from .strategies.slots import apply_slots
from .strategies.bools import apply_bool_packing
from .strategies.strings import apply_string_interning
from .strategies.compacts import apply_compact_fields, classify_int_range
from .strategies.adaptive import AdaptiveMonitor
from .report import MemoryReport
from .utils import deep_size, get_annotations

T = TypeVar("T")


@dataclass
class ThriftConfig:
    slots: bool = True
    pack_bools: bool = True
    intern_strings: bool = True
    compact_ints: bool = True
    compact_floats: bool = True
    check_overflow: bool = False
    adaptive: bool = False
    adaptive_sample: int = 500
    profile: bool = True


class ThriftMeta:
    """
    Holds optimization metadata attached to a thriftified class.
    """
    def __init__(self, original_cls, config: ThriftConfig):
        self.original_cls = original_cls
        self.config = config
        self.strategies_applied: list[str] = []
        self.original_size: int | None = None
        self.optimized_size: int | None = None
        self._adaptive_monitor: AdaptiveMonitor | None = None

    def report(self) -> MemoryReport:
        return MemoryReport(
            class_name=self.original_cls.__name__,
            strategies=self.strategies_applied,
            original_size=self.original_size,
            optimized_size=self.optimized_size,
            field_info=getattr(self, "_field_info", {}),
        )


@overload
def thrift(cls: Type[T]) -> Type[T]: ...
@overload
def thrift(
    *,
    slots: bool = True,
    pack_bools: bool = True,
    intern_strings: bool = True,
    compact_ints: bool = True,
    compact_floats: bool = True,
    check_overflow: bool = False,
    adaptive: bool = False,
    adaptive_sample: int = 500,
    profile: bool = True,
) -> Any: ...


def thrift(
    cls: Type[T] | None = None,
    *,
    slots: bool = True,
    pack_bools: bool = True,
    intern_strings: bool = True,
    compact_ints: bool = True,
    compact_floats: bool = True,
    check_overflow: bool = False,
    adaptive: bool = False,
    adaptive_sample: int = 500,
    profile: bool = True,
):
    config = ThriftConfig(
        slots=slots,
        pack_bools=pack_bools,
        intern_strings=intern_strings,
        compact_ints=compact_ints,
        compact_floats=compact_floats,
        check_overflow=check_overflow,
        adaptive=adaptive,
        adaptive_sample=adaptive_sample,
        profile=profile,
    )

    def decorator(cls: Type[T]) -> Type[T]:
        return _apply_thrift(cls, config)

    if cls is not None:
        # called as @thrift without arguments
        return decorator(cls)

    return decorator


def _apply_thrift(cls: Type[T], config: ThriftConfig, compact_overrides: dict | None = None) -> Type[T]:
    """Apply all configured optimizations to a class."""
    meta = ThriftMeta(cls, config)
    annotations = get_annotations(cls)
    field_info: dict[str, dict] = {name: {"type": t, "optimizations": []} for name, t in annotations.items()}

    if config.profile:
        meta.original_size = _estimate_size(cls, annotations)

    new_cls = cls

    # 1. __slots__
    if config.slots:
        new_cls = apply_slots(new_cls, annotations)
        meta.strategies_applied.append("slots")

    # 2. Compact ints/floats (removes int/float from slots, adds __compact_buffer__)
    if config.compact_ints or config.compact_floats:
        new_cls, compact_opts = apply_compact_fields(new_cls, annotations, config, compact_overrides)
        if compact_opts:
            meta.strategies_applied.append("compact_ints")
            for f, opt in compact_opts.items():
                field_info[f]["optimizations"].append(opt)

    # 3. Bool packing (removes bools from slots, packs into _bool_flags)
    bool_fields = [name for name, t in annotations.items() if t is bool or t == "bool"]
    if config.pack_bools and len(bool_fields) >= 2:
        new_cls = apply_bool_packing(new_cls, bool_fields, annotations, slots_enabled=config.slots)
        meta.strategies_applied.append("bool_packing")
        for f in bool_fields:
            field_info[f]["optimizations"].append("packed into bitfield")

    # 4. String interning
    str_fields = [name for name, t in annotations.items() if t is str or t == "str"]
    if config.intern_strings and str_fields:
        new_cls = apply_string_interning(new_cls, str_fields)
        meta.strategies_applied.append("string_interning")
        for f in str_fields:
            field_info[f]["optimizations"].append("interned")

    if config.profile:
        meta.optimized_size = _estimate_size(new_cls, annotations)

    # 5. Adaptive monitor (after size estimation to avoid contamination)
    if config.adaptive:
        monitor = AdaptiveMonitor(new_cls, config, annotations)
        new_cls = monitor.wrap(new_cls)
        meta._adaptive_monitor = monitor
        meta.strategies_applied.append("adaptive")
    meta._field_info = field_info

    new_cls.__thrift_meta__ = meta
    new_cls.__thrift_config__ = config
    new_cls.memory_report = classmethod(lambda cls_: meta.report())
    def _optimize(cls):
        """Rebuild class with adaptive recommendations applied.

        Call after the monitor has collected enough samples.
        Returns a new class with narrower compact types (e.g. int16, float32)
        based on observed field ranges. Existing instances keep the old layout.
        """
        return _apply_optimizations(cls, meta)
    new_cls.optimize = classmethod(_optimize)

    return new_cls


def _apply_thrift_with_overrides(cls: Type[T], config_overrides: dict, type_map: dict) -> Type[T]:
    """Re-apply thrift with specific compact type overrides (used by adaptive monitor)."""
    config = ThriftConfig(**config_overrides)
    return _apply_thrift(cls, config, compact_overrides=type_map)


def _apply_optimizations(cls, meta: ThriftMeta):
    """Rebuild class with adaptive recommendations applied."""
    from .strategies.adaptive import AdaptiveMonitor
    monitor = getattr(cls, "__adaptive_monitor__", None)
    if monitor is None:
        return cls
    report = monitor.get_report()
    if not report.get("fields"):
        return cls

    type_map = {}
    from .strategies.compacts import classify_int_range
    for fname, info in report["fields"].items():
        if info.get("type") == "int" and "observed_min" in info:
            compact = classify_int_range(info["observed_min"], info["observed_max"])
            type_map[fname] = compact
        elif info.get("type") == "float" and "max_abs_value" in info:
            if info["max_abs_value"] < 3.4e38:
                type_map[fname] = ("float32", "f")
            else:
                type_map[fname] = ("float64", "d")

    if not type_map:
        return cls

    config = meta.config
    overrides = dict(
        slots=config.slots,
        pack_bools=config.pack_bools,
        intern_strings=config.intern_strings,
        compact_ints=True,
        compact_floats=True,
        check_overflow=False,
        adaptive=False,
        profile=config.profile,
    )
    return _apply_thrift_with_overrides(meta.original_cls, overrides, type_map)


def _estimate_size(cls: Type, annotations: dict) -> int:
    try:
        dummy_kwargs = {}
        for name, t in annotations.items():
            if t is int or t == "int":
                dummy_kwargs[name] = 0
            elif t is float or t == "float":
                dummy_kwargs[name] = 0.0
            elif t is str or t == "str":
                dummy_kwargs[name] = ""
            elif t is bool or t == "bool":
                dummy_kwargs[name] = False
            else:
                dummy_kwargs[name] = None

        if dataclasses.is_dataclass(cls):
            obj = cls(**dummy_kwargs)
        else:
            try:
                obj = cls(**dummy_kwargs)
            except TypeError:
                obj = object.__new__(cls)
                for slot in getattr(cls, "__slots__", ()):
                    if slot == "__compact_buffer__":
                        object.__setattr__(obj, "__compact_buffer__",
                                           bytearray(getattr(cls, "__compact_buffer_size__", 0)))
                    elif slot == "_bool_flags":
                        object.__setattr__(obj, "_bool_flags", 0)
                for k, v in dummy_kwargs.items():
                    try:
                        object.__setattr__(obj, k, v)
                    except Exception:
                        pass

        return deep_size(obj)
    except Exception:
        return 0
