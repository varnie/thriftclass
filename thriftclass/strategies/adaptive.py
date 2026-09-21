"""Bounded, per-field observations; never retain instances or float sample lists."""

import copy
import math
import threading
from collections import Counter

from .compacts import classify_int_range

INTERN_CARDINALITY_RATIO = 0.1


class AdaptiveMonitor:
    def __init__(self, cls, config, annotations):
        self.cls = cls
        self.config = config
        self.annotations = annotations
        self.target = config.adaptive_sample
        self._str_counters = {n: Counter() for n, t in annotations.items() if t is str}
        self._int_ranges = {n: [None, None] for n, t in annotations.items() if t is int}
        self._float_max = {n: 0.0 for n, t in annotations.items() if t is float}
        self._field_assignment_counts = dict.fromkeys(
            [*self._str_counters, *self._int_ranges, *self._float_max], 0
        )
        self._remaining = len(self._field_assignment_counts)
        self._analysis_done = self._remaining == 0
        self._analysis_result = {}
        self._lock = threading.RLock()

    @property
    def sample_count(self):
        """Minimum successful assignments per monitored field, not instance IDs."""
        return min(self._field_assignment_counts.values(), default=0)

    def wrap(self, cls):
        monitor = self
        original_setattr = cls.__setattr__

        def __setattr__(self, name, value):
            original_setattr(self, name, value)
            if not monitor._analysis_done and name in monitor._field_assignment_counts:
                monitor._observe_field(self, name, getattr(self, name))

        cls.__setattr__ = __setattr__
        cls.__adaptive_monitor__ = monitor
        return cls

    def _observe_field(self, obj, name, value):
        with self._lock:
            if self._analysis_done or name not in self._field_assignment_counts:
                return
            count = self._field_assignment_counts[name]
            if count >= self.target:
                return
            if name in self._str_counters and isinstance(value, str):
                self._str_counters[name][value] += 1
            elif (
                name in self._int_ranges and isinstance(value, int) and not isinstance(value, bool)
            ):
                lo, hi = self._int_ranges[name]
                self._int_ranges[name] = [
                    value if lo is None else min(lo, value),
                    value if hi is None else max(hi, value),
                ]
            elif name in self._float_max and isinstance(value, (int, float)):
                magnitude = abs(value)
                self._float_max[name] = (
                    max(self._float_max[name], magnitude) if math.isfinite(magnitude) else math.inf
                )
            else:
                return
            count += 1
            self._field_assignment_counts[name] = count
            if count == self.target:
                self._remaining -= 1
                if self._remaining == 0:
                    self._analyze()

    def _analyze(self):
        result = {}
        for name, counter in self._str_counters.items():
            total = self._field_assignment_counts[name]
            if not total:
                continue
            unique = len(counter)
            ratio = unique / total
            result[name] = {
                "type": "str",
                "unique_values": unique,
                "total_observed": total,
                "cardinality_ratio": round(ratio, 3),
                "top_values": counter.most_common(5),
                "recommendation": (
                    "consider interning repeated strings"
                    if ratio <= INTERN_CARDINALITY_RATIO
                    else "consider disabling interning for high-cardinality strings"
                ),
            }
        for name, (lo, hi) in self._int_ranges.items():
            if lo is not None:
                compact = classify_int_range(lo, hi)
                result[name] = {
                    "type": "int",
                    "observed_min": lo,
                    "observed_max": hi,
                    "recommendation": f"use {compact[0]} (range {lo}..{hi})",
                }
        for name, magnitude in self._float_max.items():
            if self._field_assignment_counts[name]:
                result[name] = {
                    "type": "float",
                    "max_abs_value": magnitude,
                    "recommendation": "keep float64 to preserve precision",
                }
        self._analysis_result = result
        self._analysis_done = True

    def get_report(self):
        with self._lock:
            return {
                "samples_collected": self.sample_count,
                "analysis_complete": self._analysis_done,
                "target_samples": self.target,
                "field_assignment_counts": dict(self._field_assignment_counts),
                "fields": copy.deepcopy(self._analysis_result),
            }
