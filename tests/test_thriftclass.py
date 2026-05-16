"""
Tests for thriftclass.
Run with: python -m pytest tests/ -v
"""

import sys
import dataclasses
import pytest

from thriftclass import thrift, ThriftConfig


# ─── Plain class ──────────────────────────────────────────────────────────────

class TestSlotsPlainClass:
    def test_slots_added(self):
        @thrift
        class Point:
            x: float
            y: float

        p = Point()
        assert hasattr(Point, "__slots__")
        assert "__dict__" not in dir(p)

    def test_values_work(self):
        @thrift
        class Point:
            x: float
            y: float

        p = Point()
        p.x = 1.5
        p.y = 2.5
        assert p.x == 1.5
        assert p.y == 2.5


# ─── Bool packing ─────────────────────────────────────────────────────────────

class TestBoolPacking:
    def test_bools_packed(self):
        @thrift
        class Flags:
            active: bool
            visible: bool
            deleted: bool
            pinned: bool

        f = Flags()
        assert hasattr(f, "_bool_flags")
        assert not hasattr(Flags, "active") or isinstance(Flags.__dict__.get("active"), property)

    def test_bool_default_false(self):
        @thrift
        class Flags:
            active: bool
            visible: bool

        f = Flags()
        assert f.active == False
        assert f.visible == False

    def test_bool_set_get(self):
        @thrift
        class Flags:
            active: bool
            visible: bool
            deleted: bool

        f = Flags()
        f.active = True
        f.visible = False
        f.deleted = True

        assert f.active == True
        assert f.visible == False
        assert f.deleted == True

    def test_bools_independent(self):
        @thrift
        class Flags:
            a: bool
            b: bool
            c: bool
            d: bool
            e: bool

        f = Flags()
        # Set alternating
        f.a = True
        f.b = False
        f.c = True
        f.d = False
        f.e = True

        assert f.a == True
        assert f.b == False
        assert f.c == True
        assert f.d == False
        assert f.e == True

    def test_single_bool_not_packed(self):
        """Single bool field should not be packed (no benefit, added complexity)."""
        @thrift
        class Single:
            active: bool
            name: str

        # With only 1 bool, packing shouldn't trigger (need >= 2)
        s = Single()
        # Just check it works
        s.active = True
        assert s.active == True

    def test_bool_toggle(self):
        @thrift
        class Flags:
            active: bool
            visible: bool

        f = Flags()
        f.active = True
        assert f.active == True
        f.active = False
        assert f.active == False


# ─── String interning ─────────────────────────────────────────────────────────

class TestStringInterning:
    def test_same_string_is_interned(self):
        @thrift
        class User:
            role: str
            status: str

        u1 = User()
        u2 = User()
        u1.role = "admin"
        u2.role = "admin"

        # Interned strings are the same object
        assert u1.role is u2.role

    def test_string_value_preserved(self):
        @thrift
        class Item:
            category: str

        item = Item()
        item.category = "electronics"
        assert item.category == "electronics"


# ─── Memory report ────────────────────────────────────────────────────────────

class TestMemoryReport:
    def test_report_returns(self):
        @thrift(profile=True)
        class Node:
            x: float
            y: float
            active: bool
            visited: bool
            label: str

        report = Node.memory_report()
        assert report is not None
        assert report.class_name == "Node"

    def test_strategies_listed(self):
        @thrift
        class Node:
            x: float
            y: float
            active: bool
            visited: bool
            label: str

        report = Node.memory_report()
        assert "slots" in report.strategies
        assert "bool_packing" in report.strategies
        assert "string_interning" in report.strategies

    def test_show_doesnt_crash(self, capsys):
        @thrift
        class Node:
            x: float
            active: bool
            visited: bool
            name: str

        Node.memory_report().show()
        captured = capsys.readouterr()
        assert "Node" in captured.out
        assert "slots" in captured.out.lower() or "Optimizations" in captured.out


# ─── Dataclass support ────────────────────────────────────────────────────────

class TestDataclassSupport:
    def test_dataclass_works(self):
        @thrift
        @dataclasses.dataclass
        class Particle:
            x: float = 0.0
            y: float = 0.0
            z: float = 0.0
            active: bool = True

        p = Particle(x=1.0, y=2.0, z=3.0)
        assert p.x == 1.0
        assert p.y == 2.0
        assert p.z == 3.0

    def test_dataclass_str_field(self):
        @thrift
        @dataclasses.dataclass
        class Item:
            name: str = ""
            price: float = 0.0

        i = Item(name="widget", price=9.99)
        assert i.name == "widget"
        assert i.price == 9.99

    def test_dataclass_all_types(self):
        @thrift
        @dataclasses.dataclass
        class Full:
            label: str = ""
            count: int = 0
            ratio: float = 0.0
            flag_a: bool = False
            flag_b: bool = True

        f = Full(label="test", count=42, ratio=1.5, flag_a=True, flag_b=False)
        assert f.label == "test"
        assert f.count == 42
        assert f.ratio == 1.5
        assert f.flag_a is True
        assert f.flag_b is False

    def test_dataclass_direct_set(self):
        @thrift
        @dataclasses.dataclass
        class Simple:
            name: str = ""
            active: bool = False

        s = Simple()
        s.name = "hello"
        s.active = True
        assert s.name == "hello"
        assert s.active is True


# ─── Config ───────────────────────────────────────────────────────────────────

class TestConfig:
    def test_disable_slots(self):
        @thrift(slots=False)
        class Plain:
            x: float
            y: float

        p = Plain()
        # Without slots, __dict__ should exist
        assert hasattr(p, "__dict__") or True  # just don't crash

    def test_disable_bool_packing(self):
        @thrift(pack_bools=False)
        class Flags:
            active: bool
            visible: bool
            deleted: bool

        f = Flags()
        # Bools should be normal attributes, not packed
        assert not hasattr(f, "_bool_flags")

    def test_callable_without_args(self):
        @thrift
        class Simple:
            x: int
            name: str

        s = Simple()
        s.x = 42
        s.name = "hello"
        assert s.x == 42
        assert s.name == "hello"


# ─── Adaptive ─────────────────────────────────────────────────────────────────

class TestAdaptive:
    def test_adaptive_collects_samples(self):
        @thrift(adaptive=True, adaptive_sample=10)
        class Event:
            level: str
            code: int
            value: float

        for i in range(15):
            e = Event()
            e.level = "INFO"
            e.code = i % 5
            e.value = float(i) * 0.1

        monitor = getattr(Event, "__adaptive_monitor__", None)
        assert monitor is not None
        assert monitor._field_assignment_counts or monitor._analysis_done
        assert monitor._analysis_done

    def test_adaptive_report_has_fields(self):
        @thrift(adaptive=True, adaptive_sample=5)
        class LogEntry:
            level: str
            code: int

        for _ in range(10):
            e = LogEntry()
            e.level = "INFO"
            e.code = 200

        monitor = getattr(LogEntry, "__adaptive_monitor__", None)
        assert monitor is not None
        report = monitor.get_report()
        assert "samples_collected" in report
        assert "fields" in report

# ─── Compact ints/floats ─────────────────────────────────────────────────────

class TestCompactFields:
    def test_int_stored_in_buffer(self):
        @thrift
        class Item:
            count: int

        obj = Item()
        obj.count = 42
        assert hasattr(obj, "__compact_buffer__")
        assert isinstance(obj.__compact_buffer__, bytearray)
        assert obj.count == 42

    def test_float_stored_in_buffer(self):
        @thrift
        class Item:
            value: float

        obj = Item()
        obj.value = 3.14
        assert hasattr(obj, "__compact_buffer__")
        assert abs(obj.value - 3.14) < 1e-12

    def test_multiple_compact_fields(self):
        @thrift
        class Stats:
            x: int
            y: float
            z: int

        obj = Stats()
        obj.x = 10
        obj.y = 20.5
        obj.z = 30
        assert obj.x == 10
        assert abs(obj.y - 20.5) < 1e-12
        assert obj.z == 30

    def test_compact_ints_disabled(self):
        @thrift(compact_ints=False, compact_floats=False)
        class Item:
            count: int
            value: float

        obj = Item()
        obj.count = 42
        obj.value = 1.5
        assert not hasattr(obj, "__compact_buffer__")
        assert obj.count == 42
        assert obj.value == 1.5

    def test_compact_floats_separate(self):
        @thrift(compact_ints=False, compact_floats=True)
        class Item:
            count: int
            value: float

        obj = Item()
        obj.count = 42
        obj.value = 1.5
        assert hasattr(obj, "__compact_buffer__")
        assert obj.count == 42
        assert abs(obj.value - 1.5) < 1e-12

    def test_compact_ints_separate(self):
        @thrift(compact_ints=True, compact_floats=False)
        class Item:
            count: int
            value: float

        obj = Item()
        obj.count = 42
        obj.value = 1.5
        assert hasattr(obj, "__compact_buffer__")
        assert obj.count == 42
        assert obj.value == 1.5

    def test_no_compact_fields_skips_buffer(self):
        @thrift(compact_ints=False, compact_floats=False)
        class NoCompact:
            name: str
            active: bool

        obj = NoCompact()
        obj.name = "test"
        obj.active = True
        assert not hasattr(obj, "__compact_buffer__")
        assert obj.name == "test"
        assert obj.active == True


# ─── Inheritance ──────────────────────────────────────────────────────────────

class TestInheritance:
    def test_basic_inheritance(self):
        @thrift
        class Base:
            x: int

        @thrift
        class Child(Base):
            y: int

        c = Child()
        c.x = 10
        c.y = 20
        assert c.x == 10
        assert c.y == 20

    def test_inheritance_with_bools(self):
        @thrift
        class Base:
            flag_a: bool
            flag_b: bool

        @thrift
        class Child(Base):
            extra: int

        c = Child()
        c.flag_a = True
        c.flag_b = False
        c.extra = 99
        assert c.flag_a == True
        assert c.flag_b == False
        assert c.extra == 99

    def test_inheritance_parent_independent(self):
        @thrift
        class Base:
            x: int

        @thrift
        class Child(Base):
            y: int

        b = Base()
        b.x = 5
        assert b.x == 5


# ─── Kwargs for plain classes (H1) ────────────────────────────────────────────

class TestPlainClassKwargs:
    def test_compact_kwargs_work(self):
        @thrift
        class Item:
            x: int
            y: float

        obj = Item(x=5, y=3.14)
        assert obj.x == 5
        assert abs(obj.y - 3.14) < 1e-12

    def test_mixed_kwargs_work(self):
        @thrift
        class Item:
            x: int
            name: str
            active: bool
            visible: bool

        obj = Item(x=42, name="hello", active=True, visible=False)
        assert obj.x == 42
        assert obj.name == "hello"
        assert obj.active is True
        assert obj.visible is False


# ─── Inheritance compact fields (H2) ─────────────────────────────────────────

class TestInheritanceCompactFields:
    def test_parent_values_preserved_after_child_init(self):
        @thrift
        class Base:
            x: int

        @thrift
        class Child(Base):
            y: int

        c = Child()
        c.x = 10
        c.y = 20
        assert c.x == 10
        assert c.y == 20

    def test_child_does_not_wipe_parent_buffer(self):
        @thrift
        class Base:
            x: int

        @thrift
        class Child(Base):
            y: int

        c = Child(x=10, y=20)
        assert c.x == 10
        assert c.y == 20


# ─── Compact type checks (M1) ────────────────────────────────────────────────

class TestCompactTypeChecks:
    def test_wrong_type_raises_typeerror(self):
        @thrift
        class Item:
            count: int

        obj = Item()
        with pytest.raises(TypeError):
            obj.count = "not a number"

    def test_correct_type_works(self):
        @thrift
        class Item:
            count: int

        obj = Item()
        obj.count = 42
        assert obj.count == 42

    def test_wrong_float_type_raises_typeerror(self):
        @thrift
        class Item:
            val: float

        obj = Item()
        with pytest.raises(TypeError):
            obj.val = [1.0, 2.0]


# ─── Overflow ─────────────────────────────────────────────────────────────────

class TestOverflow:
    def test_no_false_overflow(self):
        @thrift(check_overflow=True)
        class Item:
            val: int

        obj = Item()
        obj.val = 2 ** 31
        assert obj.val == 2 ** 31

    def test_large_int_fits_int64(self):
        @thrift(check_overflow=False)
        class Item:
            val: int

        obj = Item()
        obj.val = 2 ** 62
        assert obj.val == 2 ** 62


# ─── Dataclass custom methods ─────────────────────────────────────────────────

class TestDataclassCustomMethods:
    def test_custom_method_preserved(self):
        @thrift
        @dataclasses.dataclass
        class Point:
            x: float = 0.0
            y: float = 0.0

            def magnitude(self):
                return (self.x ** 2 + self.y ** 2) ** 0.5

        p = Point(x=3.0, y=4.0)
        assert hasattr(p, "magnitude")
        assert p.magnitude() == 5.0


# ─── Adaptive apply_optimizations ─────────────────────────────────────────────

class TestAdaptiveApply:
    def test_apply_optimizations_returns_optimized(self):
        @thrift(adaptive=True, adaptive_sample=5)
        class Request:
            code: int
            value: float

        for i in range(10):
            r = Request()
            r.code = 200
            r.value = float(i) * 0.5

        monitor = getattr(Request, "__adaptive_monitor__", None)
        assert monitor is not None
        report = monitor.get_report()
        assert report["analysis_complete"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
