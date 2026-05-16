import sys
from collections import Counter
from typing import Type, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import ThriftConfig

T = TypeVar("T")

INTERN_CARDINALITY_RATIO = 0.1
MIN_SAMPLES = 50


class AdaptiveMonitor:
    def __init__(self, cls: Type, config: "ThriftConfig", annotations: dict):
        self.cls = cls
        self.config = config
        self.annotations = annotations
        self.target = config.adaptive_sample

        self._str_counters: dict[str, Counter] = {
            name: Counter()
            for name, t in annotations.items()
            if t is str or t == "str"
        }
        self._int_ranges: dict[str, list] = {
            name: [None, None]
            for name, t in annotations.items()
            if t is int or t == "int"
        }
        self._float_samples: dict[str, list[float]] = {
            name: []
            for name, t in annotations.items()
            if t is float or t == "float"
        }
        self._seen_instances: set = set()
        self._field_assignment_counts: dict[str, int] = {}
        self._analysis_done = False
        self._analysis_result: dict = {}

    @property
    def sample_count(self) -> int:
        return len(self._seen_instances)

    def wrap(self, cls: Type[T]) -> Type[T]:
        monitor = self
        original_setattr = cls.__dict__.get("__setattr__")

        def __setattr__(self, name, value):
            if original_setattr:
                original_setattr(self, name, value)
            else:
                object.__setattr__(self, name, value)
            monitor._observe_field(self, name, value)

        cls.__setattr__ = __setattr__
        cls.__adaptive_monitor__ = monitor
        return cls

    def _observe_field(self, obj, name: str, value):
        if self._analysis_done:
            return

        self._seen_instances.add(id(obj))

        if name in self._str_counters and isinstance(value, str):
            self._str_counters[name][value] += 1
        elif name in self._int_ranges and isinstance(value, int) and not isinstance(value, bool):
            lo, hi = self._int_ranges[name]
            self._int_ranges[name] = [
                value if lo is None else min(lo, value),
                value if hi is None else max(hi, value),
            ]
        elif name in self._float_samples and isinstance(value, float):
            self._float_samples[name].append(value)

        self._field_assignment_counts[name] = self._field_assignment_counts.get(name, 0) + 1
        total = sum(self._field_assignment_counts.values())

        if total >= self.target * len(self.annotations):
            self._analyze()

    def _analyze(self):
        from .compacts import classify_int_range
        self._analysis_done = True
        result = {}

        for fname, counter in self._str_counters.items():
            total = sum(counter.values())
            unique = len(counter)
            if total == 0:
                continue
            ratio = unique / total
            result[fname] = {
                "type": "str",
                "unique_values": unique,
                "total_observed": total,
                "cardinality_ratio": round(ratio, 3),
                "recommendation": (
                    f"intern (only {unique} unique values in {total} assignments)"
                    if ratio <= INTERN_CARDINALITY_RATIO
                    else f"skip interning ({unique} unique / {total} total, high cardinality)"
                ),
                "top_values": counter.most_common(5),
            }

        for fname, (lo, hi) in self._int_ranges.items():
            if lo is None:
                continue
            compact = classify_int_range(lo, hi)
            result[fname] = {
                "type": "int",
                "observed_min": lo,
                "observed_max": hi,
                "recommendation": (
                    f"use {compact[0]} (range {lo}..{hi})"
                    if compact
                    else f"keep int64 (range {lo}..{hi})"
                ),
            }

        for fname, values in self._float_samples.items():
            if not values:
                continue
            max_val = max(abs(v) for v in values)
            result[fname] = {
                "type": "float",
                "max_abs_value": round(max_val, 6),
                "recommendation": (
                    "could use float32 (saves 4 bytes/field, values fit)"
                    if max_val < 3.4e38
                    else "keep float64 (large values)"
                ),
            }

        self._analysis_result = result

    def get_report(self) -> dict:
        if not self._analysis_done:
            total = sum(self._field_assignment_counts.values())
            if total >= MIN_SAMPLES:
                self._analyze()
        return {
            "samples_collected": self.sample_count,
            "analysis_complete": self._analysis_done,
            "target_samples": self.target,
            "fields": self._analysis_result,
        }
