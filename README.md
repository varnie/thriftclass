# thriftclass

Experimental memory optimization for annotated Python classes. `@thrift` combines
slots, compact numeric storage, boolean bitfields, and string interning. It trades
CPU time for potential memory savings; benchmark your actual object population.
Requires Python 3.10+ and has no runtime dependencies.

## Installation

```bash
pip install git+https://github.com/varnie/thriftclass.git
```

From a local checkout:

```bash
pip install .
```

## Quick start

```python
from thriftclass import thrift


@thrift
class Point:
    x: float
    y: float
    label: str = "origin"
    active: bool = True
    visible: bool = False


p = Point(x=1.0, y=2.0)
assert (p.x, p.y, p.label, p.active) == (1.0, 2.0, "origin", True)
p.x = 3.0
Point.memory_report().show()
```

Plain classes without an initializer accept annotated field names as keyword
arguments. Unknown keywords and positional arguments raise `TypeError`. A custom
initializer retains its argument handling and runs once; its results are not
replaced with the original keyword values afterward.

Declared defaults are preserved. Undeclared defaults for compact numbers are
zero, and packed booleans start false. Other fields without defaults remain
unset until assigned. `ClassVar` and dataclass `InitVar` annotations do not
become instance slots.

## Configuration

```python
@thrift(
    slots=True,
    pack_bools=True,
    intern_strings=True,
    compact_ints=True,
    compact_floats=True,
    check_overflow=False,
    adaptive=False,
    adaptive_sample=500,
    profile=True,
)
class Record:
    count: int
    value: float
```

| Option | Behavior |
| --- | --- |
| `slots` | Allocate slots for annotated instance fields; an inherited instance dictionary cannot be removed. |
| `pack_bools` | Store two or more newly declared bool fields in a shared integer bitfield. Subclasses can extend an existing bitfield with one field. Setters use truth-value conversion. |
| `intern_strings` | Intern exact `str` values on annotated string fields. String subclasses retain their type and are not interned. |
| `compact_ints` | Store integers in signed 64-bit fields initially; values must support integer indexing. Floats are rejected with `TypeError`. |
| `compact_floats` | Store Python `int`/`float` values as 64-bit floats. |
| `check_overflow` | Retained for compatibility. Integer range checks now always run before writing, so overflow cannot corrupt the previous value. |
| `adaptive` | Collect a bounded sample of successful assignments to each numeric/string field. |
| `adaptive_sample` | Positive integer specifying observations per monitored field, not the number of distinct instances. |
| `profile` | Produce a synthetic size estimate without executing the class constructor. Disable to skip profiling work. |

Out-of-range integers raise `OverflowError`; invalid input types raise
`TypeError`. An unsuccessful numeric assignment leaves the prior value intact.
Infinities and NaNs remain valid float64 values. Fixed-width storage cannot
represent arbitrary-sized Python integers; disable `compact_ints` if needed.

## Dataclasses and inheritance

Apply `@thrift` above `@dataclass`:

```python
from dataclasses import dataclass, field


@thrift
@dataclass(frozen=True, kw_only=True)
class Config:
    port: int = 8080
    host: str = "localhost"
    tags: list = field(default_factory=list, compare=False)


config = Config(port=443)
```

The decorator preserves generated initializers, `__post_init__`, default
factories, field metadata, keyword-only parameters, comparison options, and
frozen behavior. Shallow copies share ordinary mutable user fields, as usual,
but have independent compact numeric buffers. Frozen dataclasses support
copying and pickling when their class is importable by module name.

Single inheritance is supported, including explicit `super().__init__()` and
zero-argument `super()` in methods. Thriftified descendants reuse one numeric
buffer and bitfield, with distinct offsets for new fields. Initializers follow
normal Python inheritance rules: a custom child initializer must call its
parent when that initialization is required.

Existing inherited optimizations remain active even if a subclass disables a
strategy. Multiple inheritance, redeclaring inherited instance fields, and
annotated custom descriptors are rejected with `TypeError`.

## Adaptive mode

```python
@thrift(adaptive=True, adaptive_sample=100)
class Request:
    status: int
    duration: float


for i in range(100):
    Request(status=200 + i % 2, duration=0.1)

report = Request.__adaptive_monitor__.get_report()
assert report["analysis_complete"]
OptimizedRequest = Request.optimize()
```

Sampling stops independently for each monitored field after its quota. A field
that is never assigned prevents completion; `.optimize()` returns the existing
class until every field has enough observations. Reports include per-field
assignment counts, and `samples_collected` is the minimum of those counts.
Repeated writes to the same instance count as observations. Failed writes do not.
Frozen dataclass construction records final field values once per initializer.

The monitor retains at most `adaptive_sample` distinct strings per string field,
integer ranges, and a running maximum for floats. It does not retain instances,
object IDs, or lists of float samples. Reads of the report do not end sampling.

`.optimize()` returns a new class with narrower integer storage based on observed
ranges and declared integer defaults. Existing instances keep their layout.
Future outliers raise `OverflowError`; samples cannot guarantee future ranges.
Float storage remains float64 to preserve precision, and disabled strategies
stay disabled. String recommendations are informational, not automatically
applied. No optimization runs automatically in the background.

## Memory reporting

```python
from thriftclass.utils import deep_size

objects = [Point(x=float(i), y=float(i + 1)) for i in range(1000)]
print(deep_size(objects))
```

`deep_size()` follows builtin containers, instance dictionaries, and slots across
the inheritance chain. It handles cycles and counts shared objects once within
one traversal. It approximates retained Python-object memory; it is not process
RSS and excludes allocator fragmentation, class/function graphs, and external
allocations.

`memory_report()` uses synthetic field values and includes buffer overhead.
It is a layout estimate, not a prediction for your production data. Missing
estimates are `None`; negative `saved_bytes`/`saved_percent` mean an increase.
Use `deep_size()` on a representative collection to account for shared strings
and other shared values across instances.

## Performance

The decorator builds each class layout once. Numeric properties use cached
`struct.Struct` objects; inheritance does not duplicate storage slots. Attribute
access and construction still cost more CPU time than ordinary slots.

The included benchmark creates 10,000 objects with three floats, an integer,
two booleans, and a label drawn from ten string values. One local CPython 3.12.13
run produced:

| Layout | Retained collection bytes | Construction | Float read | Float write |
| --- | ---: | ---: | ---: | ---: |
| Instance dictionary | 3,325,545 | 9.8 ms | 64 ns | 130 ns |
| Standard dataclass slots | 2,445,232 | 10.0 ms | 63 ns | 117 ns |
| `thriftclass` | 1,535,684 | 109.9 ms | 228 ns | 845 ns |

For this workload, thrift used about 37% less retained memory than slots, with
roughly 11× construction cost and 4–7× attribute-access cost. These are local
measurements, not guarantees. Timings include Python call overhead; see the
benchmark for the complete methodology. Small classes or already-shared values
can consume **more** memory after packing because each buffer has overhead.

Run it after installing the checkout:

```bash
python benchmarks/benchmark.py --instances 10000 --operations 100000
```

## Limitations

- This remains an experimental proof of concept with an unstable API.
- Decoration returns a new class, even with `slots=False`. References to the
  original class are not updated. Class creation hooks may run again; custom
  metaclasses, framework models, and custom serialization protocols are not
  generally supported.
- Annotation resolution can fail for local forward references. Unresolved
  fields remain ordinary storage instead of receiving numeric optimization.
- Slot-based layouts reject undeclared attributes and generally remove weak
  references unless an existing or inherited weak-reference slot is present.
- `__compact_buffer__`, `_bool_flags`, `__compact_buffer_size__`,
  `__adaptive_monitor__`, `memory_report`, and `optimize` are reserved. Other
  `__thrift_*` attributes are implementation metadata.
- String interning is useful only when values repeat. High-cardinality values
  still incur lookup overhead and need representative memory measurements;
  interning does not promise a particular object lifetime across Python versions.
- Individual adaptive observations are synchronized; compound updates to user
  fields and packed booleans are not an application-level concurrency guarantee.
- Disabling a strategy is often the best optimization when its CPU or memory
  overhead outweighs the measured benefit.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
ruff check .
ruff format --check .
python demo.py
```

CI runs tests on Python 3.10–3.13. Regression coverage includes constructor
behavior, defaults, dataclass options, inheritance, `super()`, numeric errors,
copy/pickle behavior, memory accounting, and bounded adaptive sampling.

## License

MIT
