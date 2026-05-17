# thriftclass

Automatic memory optimization for Python classes. Apply `@thrift` and get `__slots__`, packed bools, interned strings, and compact int/float storage — no manual refactoring.

## Install

copy `thriftclass/` into your project.

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
HttpRequest = HttpRequest.optimize()
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

Six strategies run in sequence, each transforming the class and passing it to the next:

### 1. `__slots__` — eliminates `__dict__`

Recreates the class via `type(name, bases, namespace)` with `__slots__` set to all annotated field names. The per-instance `__dict__` (~40% of instance memory) is removed. Old class members are copied into the new namespace. For dataclasses on Python 3.10+, uses `dataclass(slots=True)` to preserve defaults.

### 2. Compact storage — `int`/`float` → bytearray buffer

Each `int`/`float` field becomes a `property` whose getter/setter call `struct.pack_into`/`unpack_from` on a shared `bytearray`. A Python `int` (~28 B) becomes an 8‑byte `int64`; a `float` (~24 B) becomes an 8‑byte `float64`. The buffer is lazily initialized on first access with resize-if-too-small logic for inheritance. Field order and offset tracking ensure parent and child fields don't overlap.

### 3. Bool packing — N bools → 1 bitfield

Bool slots are replaced with `property` descriptors that read/write individual bits of a single `_bool_flags` integer slot via bitmasks (`self._bool_flags |= 1 << bit`). Inheritance assigns unique bit offsets per level by querying the parent's `__thrift_bit_map__`, so child bits don't collide with parent bits. Only classes with ≥2 bool fields are packed.

### 4. String interning — deduplicates strings

Patches `__setattr__` and `__init__` in-place (no class recreation, avoiding `__slots__` conflicts). Every string value assigned to an interned field is run through `sys.intern()`, so identical strings (e.g. `"INFO"` across thousands of log entries) share one object. Safe for low-cardinality fields; high-cardinality fields (timestamps, UUIDs) leak memory since interned strings live for the process lifetime.

### 5. Adaptive monitor — learns from real data

Wraps the class to collect field values during normal usage. After enough samples, analyses ranges and cardinality, then rebuilds the class with tighter types (e.g. `int16` instead of `int64`, `float32` instead of `float64`, interning for low-cardinality strings). Call `.optimize()` on the class to get the rebuilt version — existing instances keep the old layout.

### 6. `memory_report()` — human-readable summary

Prints a bordered table showing bytes before/after, which strategies applied, and per-field storage details. Available as a classmethod on any thriftified class.

## Limitations

- **Inheritance**: parent and child share a single compact buffer for `int`/`float` fields. Bool packing uses independent bit offsets per level, so bools don't collide. Avoid overriding `__init__` manually in thriftified subclasses.
- **String interning**: high-cardinality strings (timestamps, UUIDs, unique messages) accumulate in the intern table forever — they're never GC'd. Disable with `intern_strings=False` for such fields.
- **Overflow**: `int` values beyond `int64` range (±9.2×10¹⁸) raise `struct.error`. Enable `check_overflow=True` for early detection.
- **Dataclass**: works when `@thrift` is placed **above** `@dataclass` (`@thrift` / `@dataclass`). The opposite order may fail because thrift modifies annotations before dataclass processes them.
- The adaptive monitor rebuilds the class via a *new* type — existing instances keep the old layout. Call `.optimize()` before creating production instances.

## Tests

```bash
python -m pytest tests/ -v
```
