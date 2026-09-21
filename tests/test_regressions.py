"""Public behavior and resource bounds not covered by the original tests."""

import dataclasses
import math
import sys
from typing import ClassVar

import pytest

from thriftclass import thrift
from thriftclass.report import MemoryReport
from thriftclass.utils import deep_size


def test_plain_defaults_and_class_variables():
    @thrift
    class Item:
        category: ClassVar[str] = "shared"
        count: int = 7
        active: bool = True
        visible: bool = False
        label: str = "default"

    obj = Item()
    assert (obj.count, obj.active, obj.visible, obj.label) == (7, True, False, "default")
    assert Item.category == "shared"
    assert "category" not in Item.__slots__


def test_defaults_without_numeric_optimization():
    @thrift(compact_ints=False)
    class Item:
        count: int = 7

    assert Item().count == 7
    assert Item(count=8).count == 8


def test_custom_init_runs_once_and_values_are_not_overwritten():
    calls = []

    @thrift(profile=False)
    class Item:
        count: int
        active: bool
        visible: bool
        label: str

        def __init__(self, count, active, visible, label):
            calls.append("init")
            self.count = count * 2
            self.active = not active
            self.visible = visible
            self.label = label.upper()

    obj = Item(count=3, active=True, visible=True, label="hello")
    assert calls == ["init"]
    assert (obj.count, obj.active, obj.visible, obj.label) == (6, False, True, "HELLO")


def test_inherited_init_super_and_methods():
    calls = []

    @thrift(profile=False)
    class Base:
        x: int
        a: bool
        b: bool

        def __init__(self, x):
            calls.append("base")
            self.x = x
            self.a = True
            self.b = False

        def value(self):
            return self.x

    @thrift(profile=False)
    class Child(Base):
        y: int
        c: bool
        d: bool

        def __init__(self, x, y):
            super().__init__(x)
            calls.append("child")
            self.y = y
            self.c = True
            self.d = False

        def value(self):
            return super().value() + self.y

    obj = Child(10, 20)
    assert calls == ["base", "child"]
    assert obj.value() == 30
    assert (obj.a, obj.b, obj.c, obj.d) == (True, False, True, False)
    assert "__compact_buffer__" not in Child.__slots__
    assert "_bool_flags" not in Child.__slots__
    assert Child.__compact_buffer_size__ == 16


def test_three_level_inheritance_does_not_repeat_fields():
    @thrift
    class A:
        x: int
        a: bool
        b: bool

    @thrift
    class B(A):
        y: int
        c: bool
        d: bool

    @thrift
    class C(B):
        z: int
        e: bool
        f: bool

    obj = C(x=1, y=2, z=3, a=True, b=False, c=False, d=True, e=True, f=False)
    assert (obj.x, obj.y, obj.z) == (1, 2, 3)
    assert (obj.a, obj.b, obj.c, obj.d, obj.e, obj.f) == (True, False, False, True, True, False)
    assert C.__compact_buffer_size__ == 24
    assert len(C.__thrift_bit_map__) == 6


def test_dataclass_features_preserved():
    @thrift
    @dataclasses.dataclass(order=True, kw_only=True)
    class Item:
        count: int = dataclasses.field(default=3, repr=False, metadata={"unit": "items"})
        values: list = dataclasses.field(default_factory=list, compare=False)
        ignored: int = dataclasses.field(default=7, init=False, compare=False)

        def __post_init__(self):
            self.count *= 2

    a, b = Item(count=2), Item(count=3)
    assert a < b
    assert a.count == 4
    assert a.ignored == 7
    assert a.values is not b.values
    assert "count=" not in repr(a)
    assert dataclasses.fields(Item)[0].metadata == {"unit": "items"}
    with pytest.raises(TypeError):
        Item(2)
    assert dataclasses.asdict(a) == {"count": 4, "values": [], "ignored": 7}


def test_frozen_dataclass_stays_frozen_and_hashable():
    @thrift
    @dataclasses.dataclass(frozen=True)
    class Item:
        count: int = 7
        a: bool = True
        b: bool = False
        label: str = "hello"

    obj = Item()
    assert obj.count == 7
    assert hash(obj) == hash(Item())
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.count = 8
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.label = "changed"
    assert dataclasses.replace(obj, count=8).count == 8


def test_dataclass_initvar_and_postinit():
    @thrift
    @dataclasses.dataclass
    class Item:
        initial: dataclasses.InitVar[int]
        count: int = 0

        def __post_init__(self, initial):
            self.count = initial * 2

    assert Item(4).count == 8
    assert "initial" not in Item.__slots__


def test_existing_slots_and_non_thrift_subclass_defaults():
    @thrift
    class Slotted:
        __slots__ = "count"
        count: int

    assert Slotted(count=42).count == 42

    @thrift
    class Base:
        count: int = 9

    class Child(Base):
        pass

    assert Child().count == 9


def test_unpacked_private_field():
    @thrift
    class Item:
        _value: str = "ok"

    assert Item()._value == "ok"


def test_inherited_setattr_is_respected():
    events = []

    class Base:
        def __setattr__(self, name, value):
            events.append(name)
            object.__setattr__(self, name, value)

    @thrift(slots=False, profile=False)
    class Child(Base):
        label: str

    obj = Child()
    obj.label = "hello"
    assert events == ["label"]


def test_plain_invalid_constructor_arguments():
    @thrift
    class Item:
        count: int

    with pytest.raises(TypeError):
        Item(3)
    with pytest.raises(TypeError):
        Item(unknown=3)


def test_numeric_errors_and_atomic_assignment():
    @thrift
    class Item:
        count: int

    obj = Item(count=42)
    with pytest.raises(TypeError):
        obj.count = 1.5
    assert obj.count == 42
    with pytest.raises(OverflowError):
        obj.count = 2**64
    assert obj.count == 42


def test_profile_does_not_invoke_constructor():
    calls = []

    @thrift
    class Item:
        count: int

        def __init__(self, count):
            calls.append(count)
            self.count = count

    assert calls == []
    assert Item.memory_report().original_size is not None
    assert Item(7).count == 7
    assert calls == [7]


def test_disabled_profile_and_negative_savings(capsys):
    @thrift(profile=False)
    class Item:
        count: int

    report = Item.memory_report()
    assert report.saved_bytes is None
    assert report.saved_percent is None
    report.show()
    assert "not available" in capsys.readouterr().out
    report = MemoryReport("Growing", [], 100, 150)
    assert report.saved_bytes == -50
    assert report.saved_percent == -50.0


def test_deep_size_containers_shared_values_and_cycles():
    payload = bytearray(1000)
    obj = [payload, payload]
    obj.append(obj)
    assert deep_size(obj) == sys.getsizeof(obj) + sys.getsizeof(payload)
    mapping = {"payload": payload}
    assert deep_size(mapping) == sum(map(sys.getsizeof, (mapping, "payload", payload)))


def test_deep_size_inherited_slots():
    class Base:
        __slots__ = "a"

    class Child(Base):
        __slots__ = ("b",)

    obj = Child()
    obj.a, obj.b = bytearray(1000), bytearray(2000)
    assert deep_size(obj) == sum(map(sys.getsizeof, (obj, obj.a, obj.b)))


def test_adaptive_sampling_is_bounded_and_per_field():
    @thrift(adaptive=True, adaptive_sample=3, profile=False)
    class Item:
        count: int
        value: float
        label: str

    obj = Item()
    for i in range(100):
        obj.count = i
        obj.label = str(i)
    monitor = Item.__adaptive_monitor__
    assert not monitor.get_report()["analysis_complete"]
    assert monitor._field_assignment_counts["count"] == 3
    assert len(monitor._str_counters["label"]) == 3
    for i in range(3):
        obj.value = float(i)
    report = monitor.get_report()
    assert report["analysis_complete"]
    assert report["samples_collected"] == 3
    report["fields"]["count"]["observed_max"] = 999
    assert monitor.get_report()["fields"]["count"]["observed_max"] == 2


def test_adaptive_preserves_float_precision_and_config():
    @thrift(adaptive=True, adaptive_sample=2, check_overflow=True, profile=False)
    class Item:
        count: int
        value: float

    for _ in range(2):
        Item(count=7, value=0.1)
    Optimized = Item.optimize()
    assert Optimized is not Item
    assert Optimized.__thrift_config__.check_overflow is True
    assert Optimized(count=7, value=0.1).value == 0.1
    with pytest.raises(OverflowError):
        Optimized(count=1000)


def test_adaptive_does_not_enable_disabled_storage():
    @thrift(adaptive=True, adaptive_sample=1, compact_floats=False, profile=False)
    class Item:
        count: int
        value: float

    Item(count=7, value=0.1)
    Optimized = Item.optimize()
    assert Optimized.__thrift_config__.compact_floats is False
    assert "value" not in Optimized.__thrift_compact_fields__


def test_optimize_waits_for_every_field():
    @thrift(adaptive=True, adaptive_sample=1)
    class Item:
        count: int
        label: str

    Item(count=7)
    assert Item.optimize() is Item


def test_adaptive_nonfinite_values_do_not_narrow():
    @thrift(adaptive=True, adaptive_sample=1)
    class Item:
        count: int
        value: float

    Item(count=7, value=math.nan)
    Optimized = Item.optimize()
    assert math.isnan(Optimized(value=math.nan).value)


@pytest.mark.parametrize("target", [0, -1, 1.5, True])
def test_invalid_sample_target(target):
    with pytest.raises((TypeError, ValueError)):
        thrift(adaptive=True, adaptive_sample=target)


def test_slots_false_does_not_mutate_original_class():
    class Item:
        count: int

    Optimized = thrift(Item, slots=False, profile=False)
    assert Optimized is not Item
    assert "count" not in vars(Item)
    assert "__thrift_meta__" not in vars(Item)
    assert Optimized(count=3).count == 3


def test_unsupported_layouts_fail_at_decoration():
    class A:
        pass

    class B:
        pass

    with pytest.raises(TypeError, match="multiple inheritance"):

        @thrift
        class C(A, B):
            count: int

    with pytest.raises(TypeError, match="reserved"):

        @thrift
        class Reserved:
            _bool_flags: int


def test_shallow_copy_has_independent_numeric_storage():
    import copy

    @thrift
    class Item:
        count: int
        data: list

    original = Item(count=7, data=[])
    cloned = copy.copy(original)
    cloned.count = 42
    assert original.count == 7
    assert cloned.data is original.data


def test_dataclass_init_false_is_preserved():
    @thrift
    @dataclasses.dataclass(init=False)
    class Item:
        count: int = 7

    assert Item().count == 7
    with pytest.raises(TypeError):
        Item(count=9)


def test_adaptive_frozen_dataclass():
    @thrift(adaptive=True, adaptive_sample=2)
    @dataclasses.dataclass(frozen=True)
    class Item:
        count: int

    Item(7)
    Item(8)
    assert Item.__adaptive_monitor__.get_report()["analysis_complete"]
    assert Item.optimize()(9).count == 9


@thrift
@dataclasses.dataclass(frozen=True)
class PickleItem:
    count: int = 7
    label: str = "hello"


def test_frozen_dataclass_pickle_and_deepcopy():
    import copy
    import pickle

    obj = PickleItem(42)
    assert pickle.loads(pickle.dumps(obj)) == obj
    assert copy.deepcopy(obj) == obj


def test_adaptive_keeps_declared_default_in_range():
    @thrift(adaptive=True, adaptive_sample=1)
    class Item:
        count: int = 1000

    Item(count=1)
    Optimized = Item.optimize()
    assert Optimized().count == 1000
