# thriftclass

Automatic memory optimization for Python classes. Apply `@thrift` and get `__slots__`, packed bools, interned strings, and compact int/float storage — no manual refactoring.

## Install

```bash
pip install thriftclass
```

Or copy `thriftclass/` into your project.

## Quick start

```python
from thriftclass import thrift

@thrift
class Point:
    x: float
    y: float
    label: str
    active: bool
    visible: bool

p = Point()
p.x = 1.0; p.y = 2.0
p.label = "origin"
p.active = True; p.visible = False

Point.memory_report().show()
```

## Optimizations

| Strategy | Default | Effect |
|---|---|---|
| `__slots__` | on | Eliminates per-instance `__dict__` (~200+ bytes saved) |
| Bool packing | on | Packs multiple `bool` fields into a single integer bitfield |
| String interning | on | Deduplicates repeated string values via `sys.intern()` |
| Compact ints | on | Stores `int` fields in a `bytearray` buffer instead of Python objects (28→8 bytes each) |
| Compact floats | on | Stores `float` fields in a `bytearray` buffer instead of Python objects (24→8 bytes each) |
| Adaptive | off | Monitors real data, then reports — or auto-applies — optimal types (e.g. `int16` instead of `int64`) |

## Configuration

```python
@thrift(slots=True, pack_bools=True, intern_strings=True,
        compact_ints=True, compact_floats=True)
class MyClass:
    ...

@thrift(slots=False)          # disable __slots__
@thrift(pack_bools=False)     # keep bools as regular attributes
@thrift(compact_ints=False)   # keep ints as Python objects
@thrift(compact_floats=False) # keep floats as Python objects
@thrift(check_overflow=True)  # raise OverflowError on int out of range
```

### Adaptive mode

```python
@thrift(adaptive=True, adaptive_sample=100)
class HttpRequest:
    method: str
    status: int
    duration: float
    path: str

# create real instances — the monitor collects statistics
for _ in range(120):
    r = HttpRequest()
    r.method = ...
    ...

# view analysis
report = HttpRequest.__adaptive_monitor__.get_report()

# rebuild with optimal types (int16, float32, etc.)
HttpRequest = HttpRequest.apply_optimizations()
```

### Dataclass support

```python
from dataclasses import dataclass

@thrift
@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    debug: bool = False
    verbose: bool = False
```

## Memory report

```python
@thrift
class Node:
    x: float
    y: float
    z: float
    visited: bool
    active: bool
    label: str
    depth: int

Node.memory_report().show()
```

Output:

```
┌──────────────────────────────────────────────────────────┐
│  thriftclass — Node                                      │
├──────────────────────────────────────────────────────────┤
│  Memory per instance:                                    │
│    Before :   344 bytes                                  │
│    After  :   214 bytes                                  │
│    Saved  :   130 bytes  (37.8%)                         │
├──────────────────────────────────────────────────────────┤
│  Optimizations applied:                                  │
│    ✓  __slots__           eliminates per-object __dict__ │
│    ✓  compact ints/floats  stored in bytearray buffer    │
│    ✓  bool → bitfield     packs bool fields into one int │
│    ✓  str interning       interned strings share memory  │
├──────────────────────────────────────────────────────────┤
│  Fields:                                                 │
│    x               → float64 (8 bytes in buffer)         │
│    y               → float64 (8 bytes in buffer)         │
│    visited         → packed into bitfield                │
│    label           → interned                            │
│    depth           → int64 (8 bytes in buffer)           │
└──────────────────────────────────────────────────────────┘
```

## How it works

1. **`__slots__`** — recreates the class with `__slots__`, removing the per-instance `__dict__`.
2. **Compact storage** — `int`/`float` fields are stored in a shared `bytearray` buffer via descriptors. Python `int` objects (28 bytes) become 8-byte `int64` values; Python `float` objects (24 bytes) become 8-byte `float64` values.
3. **Bool packing** — bool fields become properties reading/writing bits in a single integer slot.
4. **String interning** — `__setattr__` is patched to call `sys.intern()` on string values, so identical strings share one object.
5. **Adaptive** — samples real field values, analyses ranges/cardinality, then rebuilds the class with optimal types (e.g. `int16`, `float32`).

## Limitations

- **Inheritance**: works but parent/child share a single compact buffer. Avoid overriding `__init__` manually in thriftified subclasses.
- **Overflow**: `int` values beyond `int64` range (±9.2×10¹⁸) raise `struct.error`. Enable `check_overflow=True` for early detection.
- **Dataclass**: works when `@thrift` is placed **above** `@dataclass` (`@thrift` / `@dataclass`). The opposite order may fail because thrift modifies annotations before dataclass processes them.
- The adaptive monitor rebuilds the class via a *new* type — existing instances keep the old layout. Call `apply_optimizations()` before creating production instances.

## Tests

```bash
python -m pytest tests/ -v
```
