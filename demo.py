"""
thriftclass — demo
==================
Shows memory savings and features across different use cases.
"""

import sys
import dataclasses

from thriftclass import thrift
from thriftclass.utils import deep_size as _deep_size


# ─── 1. Graph node — millions of these in memory ──────────────────────────────

print("\n" + "=" * 60)
print("  Example 1: Graph Node")
print("=" * 60)

class NodeBefore:
    def __init__(self, x, y, z, visited, active, label, depth):
        self.x = x; self.y = y; self.z = z
        self.visited = visited; self.active = active
        self.label = label; self.depth = depth

@thrift
class Node:
    x: float
    y: float
    z: float
    visited: bool
    active: bool
    label: str
    depth: int

before = NodeBefore(1.0, 2.0, 3.0, False, True, "node_a", 5)
after  = Node()
after.x = 1.0; after.y = 2.0; after.z = 3.0
after.visited = False; after.active = True
after.label = "node_a"; after.depth = 5

print(f"  Before : {_deep_size(before)} bytes")
print(f"  After  : {_deep_size(after)} bytes  (slots, bitfield bools, compact ints/floats)")
print(f"  has __slots__  : {hasattr(Node, '__slots__')}")
print(f"  bool packed    : {hasattr(after, '_bool_flags')}")
print(f"  visited        : {after.visited}  active: {after.active}")

Node.memory_report().show()


# ─── 2. Log entry — high-volume, low-cardinality strings ─────────────────────

print("\n" + "=" * 60)
print("  Example 2: Log Entry (string interning demo)")
print("=" * 60)

@thrift
class LogEntry:
    level: str
    service: str
    message: str
    code: int

e1 = LogEntry(); e1.level = "INFO";  e1.service = "auth"; e1.message = "login ok"; e1.code = 200
e2 = LogEntry(); e2.level = "INFO";  e2.service = "auth"; e2.message = "login ok"; e2.code = 200
e3 = LogEntry(); e3.level = "ERROR"; e3.service = "db";   e3.message = "timeout";  e3.code = 500

print(f"  e1.level is e2.level  → {e1.level is e2.level}  (same interned object!)")
print(f"  e1.service is e2.service → {e1.service is e2.service}")
print(f"  e1.level == 'INFO'    → {e1.level == 'INFO'}")
print(f"  e3.level == 'ERROR'   → {e3.level == 'ERROR'}")


# ─── 3. Particle system — bool packing deep dive ─────────────────────────────

print("\n" + "=" * 60)
print("  Example 3: Particle System (bool packing)")
print("=" * 60)

@thrift
class Particle:
    x: float
    y: float
    active: bool
    visible: bool
    collidable: bool
    static: bool
    sleeping: bool

p = Particle()
p.x = 10.5; p.y = 20.3
p.active = True; p.visible = True
p.collidable = True; p.static = False; p.sleeping = False

print(f"  5 bools → 1 int (_bool_flags = {p._bool_flags}, binary: {p._bool_flags:08b})")
print(f"  active={p.active}  visible={p.visible}  collidable={p.collidable}")
print(f"  static={p.static}  sleeping={p.sleeping}")

p.sleeping = True
print(f"  After p.sleeping=True → _bool_flags={p._bool_flags:08b}")
print(f"  sleeping={p.sleeping}  active={p.active}  (others unchanged)")


# ─── 4. Adaptive monitor — learns from real data ─────────────────────────────

print("\n" + "=" * 60)
print("  Example 4: Adaptive Monitor")
print("=" * 60)

import random

@thrift(adaptive=True, adaptive_sample=100)
class HttpRequest:
    method: str
    status: int
    duration: float
    path: str

methods = ["GET", "POST", "PUT", "DELETE"]
paths = ["/api/users", "/api/items", "/health", "/api/orders"]

for _ in range(120):
    r = HttpRequest()
    r.method   = random.choice(methods)   # low cardinality
    r.status   = random.choice([200, 201, 400, 404, 500])  # uint16 fits
    r.duration = random.uniform(0.001, 2.5)
    r.path     = random.choice(paths)     # low cardinality

monitor = HttpRequest.__adaptive_monitor__
report  = monitor.get_report()

print(f"  Samples collected : {report['samples_collected']}")
print(f"  Analysis complete : {report['analysis_complete']}")
print()
for field, info in report["fields"].items():
    print(f"  [{field}]")
    print(f"    type           : {info['type']}")
    print(f"    recommendation : {info['recommendation']}")
    if "top_values" in info:
        print(f"    top values     : {info['top_values']}")
    print()


# ─── 5. Dataclass compatibility ───────────────────────────────────────────────

print("=" * 60)
print("  Example 5: Works with @dataclass")
print("=" * 60)

@thrift
@dataclasses.dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    debug: bool = False
    verbose: bool = False
    secure: bool = True

c = Config(host="prod.server.com", port=443, secure=True)
print(f"  host={c.host}  port={c.port}")
print(f"  debug={c.debug}  verbose={c.verbose}  secure={c.secure}")
print(f"  has __slots__: {hasattr(Config, '__slots__')}")
Config.memory_report().show()

print()
print("✓ All examples complete.")
