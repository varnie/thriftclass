"""Decorate annotated classes with a single, consistent storage layout."""

from __future__ import annotations

import dataclasses
import functools
import struct
import sys
import types
from dataclasses import dataclass

from .report import MemoryReport
from .strategies.adaptive import AdaptiveMonitor
from .strategies.bools import make_bool_property
from .strategies.compacts import SAFE_DEFAULTS, _make_compact_descriptor, classify_int_range
from .strategies.slots import copy_instance, instance_state, rebuild_class, restore_state
from .strategies.strings import apply_string_interning
from .utils import deep_size, get_annotations


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

    def __post_init__(self):
        if isinstance(self.adaptive_sample, bool) or not isinstance(self.adaptive_sample, int):
            raise TypeError("adaptive_sample must be a positive integer")
        if self.adaptive_sample < 1:
            raise ValueError("adaptive_sample must be positive")


class ThriftMeta:
    def __init__(self, original_cls, config):
        self.original_cls = original_cls
        self.config = config
        self.strategies_applied = []
        self.original_size = None
        self.optimized_size = None
        self._adaptive_monitor = None
        self._field_info = {}

    def report(self):
        return MemoryReport(
            self.original_cls.__name__,
            list(self.strategies_applied),
            self.original_size,
            self.optimized_size,
            {
                k: {**v, "optimizations": list(v["optimizations"])}
                for k, v in self._field_info.items()
            },
        )


def thrift(
    cls=None,
    *,
    slots=True,
    pack_bools=True,
    intern_strings=True,
    compact_ints=True,
    compact_floats=True,
    check_overflow=False,
    adaptive=False,
    adaptive_sample=500,
    profile=True,
):
    """Optimize annotated fields; custom and dataclass initializers run once."""
    config = ThriftConfig(
        slots,
        pack_bools,
        intern_strings,
        compact_ints,
        compact_floats,
        check_overflow,
        adaptive,
        adaptive_sample,
        profile,
    )

    def decorate(cls):
        return _apply_thrift(cls, config)

    return decorate(cls) if cls is not None else decorate


def _apply_thrift(cls, config, compact_overrides=None):
    if not isinstance(cls, type):
        raise TypeError("@thrift expects a class")
    if len(cls.__bases__) > 1:
        raise TypeError("multiple inheritance is not supported")
    if "__thrift_meta__" in vars(cls):
        raise TypeError("class is already thriftified")
    annotations = get_annotations(cls)
    parent = cls.__bases__[0]
    inherited = get_annotations(parent)
    own = {name: value for name, value in annotations.items() if name not in inherited}
    for name in set(cls.__dict__.get("__annotations__", {})) | set(vars(cls)):
        if name in inherited and name in annotations:
            raise TypeError(f"overriding inherited field '{name}' is not supported")
    reserved = {
        "__compact_buffer__",
        "_bool_flags",
        "memory_report",
        "optimize",
        "__adaptive_monitor__",
        "__compact_buffer_size__",
    }
    for name in reserved:
        if name in vars(cls) or name in annotations:
            raise TypeError(f"'{name}' is reserved by thriftclass")
    for name in own:
        value = vars(cls).get(name)
        if hasattr(value, "__get__") and not isinstance(value, types.MemberDescriptorType):
            raise TypeError(f"annotated descriptor '{name}' is not supported")

    meta = ThriftMeta(cls, config)
    field_info = {name: {"type": t, "optimizations": []} for name, t in annotations.items()}
    parent_meta = getattr(parent, "__thrift_meta__", None)
    if parent_meta:
        for name, info in parent_meta._field_info.items():
            field_info[name] = {**info, "optimizations": list(info["optimizations"])}
    properties = {}
    storage = []
    compact = dict(getattr(parent, "__thrift_compact_fields__", {}))
    total_size = getattr(parent, "__compact_buffer_size__", 0)
    for name, typ in own.items():
        if not ((typ is int and config.compact_ints) or (typ is float and config.compact_floats)):
            continue
        type_name, fmt = (compact_overrides or {}).get(name, SAFE_DEFAULTS[typ])
        size = struct.calcsize("=" + fmt)
        properties[name] = _make_compact_descriptor(name, fmt, total_size)
        compact[name] = (type_name, fmt, total_size)
        total_size += size
        field_info[name]["optimizations"].append(f"{type_name} ({size} bytes in buffer)")
    if total_size:
        storage.append("__compact_buffer__")
        meta.strategies_applied.append("compact_ints")
    bit_map = dict(getattr(parent, "__thrift_bit_map__", {}))
    bool_fields = [name for name, typ in own.items() if typ is bool]
    if config.pack_bools and (len(bool_fields) >= 2 or bit_map):
        for name in bool_fields:
            bit = len(bit_map)
            bit_map[name] = bit
            properties[name] = make_bool_property(name, bit)
            field_info[name]["optimizations"].append("packed into bitfield")
    if bit_map:
        storage.append("_bool_flags")
        meta.strategies_applied.append("bool_packing")

    new_cls = rebuild_class(cls, own, properties, storage, config.slots)
    new_cls.__thrift_layout_owner__ = new_cls
    new_cls.__compact_buffer_size__ = total_size
    new_cls.__thrift_compact_fields__ = compact
    new_cls.__thrift_bit_map__ = bit_map
    new_cls.__thrift_bool_fields__ = tuple(bit_map)
    if config.slots and not new_cls.__dictoffset__:
        meta.strategies_applied.insert(0, "slots")

    defaults = dict(getattr(parent, "__thrift_defaults__", {}))
    for name in own:
        if name in vars(cls) and not isinstance(vars(cls)[name], types.MemberDescriptorType):
            defaults[name] = vars(cls)[name]
    new_cls.__thrift_defaults__ = defaults
    strings = set(getattr(parent, "__thrift_intern_fields__", ()))
    if config.intern_strings:
        strings.update(name for name, typ in own.items() if typ is str)
    if strings:
        apply_string_interning(new_cls, strings)
        meta.strategies_applied.append("string_interning")
        for name in strings:
            field_info[name]["optimizations"] = ["interned"]

    if not hasattr(new_cls, "__copy__"):
        new_cls.__copy__ = copy_instance
    frozen = dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen
    if frozen:
        if "__getstate__" not in vars(cls):
            new_cls.__getstate__ = instance_state
        if "__setstate__" not in vars(cls):
            new_cls.__setstate__ = restore_state
    original_init = new_cls.__init__
    # Plain classes without an initializer receive field-keyword construction.
    field_init = original_init is object.__init__ or (
        "__init__" not in vars(cls) and getattr(parent, "__thrift_field_init__", False)
    )
    if dataclasses.is_dataclass(cls) and not cls.__dataclass_params__.init:
        field_init = False
    new_cls.__thrift_field_init__ = field_init

    def initialize(self, *args, **kwargs):
        _initialize_storage(self, new_cls)
        if field_init:
            if args:
                raise TypeError(f"{cls.__name__} accepts field keywords only")
            unknown = kwargs.keys() - annotations.keys()
            if unknown:
                raise TypeError(f"unexpected field argument: {sorted(unknown)[0]}")
            for name, value in kwargs.items():
                setattr(self, name, value)
        else:
            original_init(self, *args, **kwargs)
        # Also handles frozen dataclass initializers using object.__setattr__.
        for name in strings:
            try:
                value = getattr(self, name)
            except AttributeError:
                continue
            if type(value) is str:
                object.__setattr__(self, name, sys.intern(value))

        if frozen and meta._adaptive_monitor is not None:
            for name in annotations:
                try:
                    value = getattr(self, name)
                except AttributeError:
                    continue
                meta._adaptive_monitor._observe_field(self, name, value)

    if not field_init:
        functools.update_wrapper(initialize, original_init)
    new_cls.__init__ = initialize
    meta._field_info = field_info
    if config.profile:
        meta.original_size = _estimate_size(cls, annotations)
        meta.optimized_size = _estimate_size(new_cls, annotations)
    if config.adaptive:
        monitor = AdaptiveMonitor(new_cls, config, annotations)
        monitor.wrap(new_cls)
        meta._adaptive_monitor = monitor
        meta.strategies_applied.append("adaptive")
    new_cls.__thrift_meta__ = meta
    new_cls.__thrift_config__ = config
    new_cls.memory_report = classmethod(lambda _: meta.report())
    new_cls.optimize = classmethod(lambda current: _apply_optimizations(current, meta))
    return new_cls


def _initialize_storage(obj, cls):
    # A child wrapper initializes the complete layout before super().__init__.
    size = cls.__compact_buffer_size__
    if size:
        try:
            object.__getattribute__(obj, "__compact_buffer__")
        except AttributeError:
            object.__setattr__(obj, "__compact_buffer__", bytearray(size))
    if cls.__thrift_bit_map__:
        try:
            object.__getattribute__(obj, "_bool_flags")
        except AttributeError:
            object.__setattr__(obj, "_bool_flags", 0)
    for name, value in cls.__thrift_defaults__.items():
        # Defaults are applied by the outermost initializer, not each super call.
        if cls is getattr(type(obj), "__thrift_layout_owner__", cls):
            object.__setattr__(obj, name, value)


def _apply_optimizations(cls, meta):
    monitor = meta._adaptive_monitor
    if monitor is None:
        return cls
    report = monitor.get_report()
    if not report["analysis_complete"]:
        return cls
    type_map = {}
    for name, info in report["fields"].items():
        if info["type"] == "int" and meta.config.compact_ints:
            lo, hi = info["observed_min"], info["observed_max"]
            default = getattr(meta.original_cls, name, None)
            if isinstance(default, int):
                lo, hi = min(lo, default), max(hi, default)
            type_map[name] = classify_int_range(lo, hi)
    if not type_map:
        return cls
    # Never silently narrow floats: fitting their magnitude does not preserve precision.
    return _apply_thrift(
        meta.original_cls, dataclasses.replace(meta.config, adaptive=False), type_map
    )


def _estimate_size(cls, annotations):
    """Synthetic layout estimate without executing user constructors."""
    if any("__del__" in vars(base) for base in cls.__mro__):
        return None
    try:
        obj = object.__new__(cls)
        if "__thrift_defaults__" in vars(cls):
            _initialize_storage(obj, cls)
        for name, typ in annotations.items():
            value = {int: 0, float: 0.0, str: "", bool: False}.get(typ)
            object.__setattr__(obj, name, value)
        return deep_size(obj)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
