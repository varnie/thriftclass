"""Reproducible current-layout benchmark; run from the repository root."""

import argparse
import dataclasses
import json
import platform
import timeit

from thriftclass import thrift
from thriftclass.utils import deep_size


@dataclasses.dataclass
class Plain:
    x: float
    y: float
    z: float
    count: int
    active: bool
    visible: bool
    label: str


Slotted = dataclasses.dataclass(
    type(
        "Slotted",
        (),
        {
            "__annotations__": dict(Plain.__annotations__),
        },
    ),
    slots=True,
)
Packed = thrift(Plain, profile=False)


def benchmark(instances, operations):
    results = {"python": platform.python_version(), "instances": instances, "layouts": {}}
    for name, cls in [("dict", Plain), ("slots", Slotted), ("thrift", Packed)]:

        def construct():
            return [
                cls(float(i), float(i + 1), float(i + 2), i + 1000, True, False, f"label-{i % 10}")
                for i in range(instances)
            ]

        objects = construct()
        obj = objects[0]
        reads = min(timeit.repeat(lambda: obj.x, number=operations, repeat=5))
        writes = min(timeit.repeat(lambda: setattr(obj, "x", 1.5), number=operations, repeat=5))
        construction = min(timeit.repeat(construct, number=1, repeat=3))
        results["layouts"][name] = {
            "retained_bytes": deep_size(objects),
            "construction_ms": round(construction * 1000, 3),
            "read_ns": round(reads * 1e9 / operations, 1),
            "write_ns": round(writes * 1e9 / operations, 1),
        }
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", type=int, default=10000)
    parser.add_argument("--operations", type=int, default=100000)
    args = parser.parse_args()
    if args.instances < 1 or args.operations < 1:
        parser.error("counts must be positive")
    print(json.dumps(benchmark(args.instances, args.operations), indent=2))
