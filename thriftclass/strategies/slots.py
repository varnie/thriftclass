"""Build a class once, preserving methods and dataclass-generated behavior."""

import functools
import types


def slot_names(cls):
    slots = cls.__dict__.get("__slots__", ())
    return (slots,) if isinstance(slots, str) else tuple(slots)


def _rebind(value, old_cls, new_cls):
    """Copy functions that close over the replaced class (notably super())."""
    if isinstance(value, types.FunctionType):
        if not value.__closure__:
            return value
        changed = False
        cells = []
        for cell in value.__closure__:
            try:
                replace = cell.cell_contents is old_cls
            except ValueError:
                replace = False
            cells.append(types.CellType(new_cls) if replace else cell)
            changed |= replace
        if not changed:
            return value
        result = types.FunctionType(
            value.__code__, value.__globals__, value.__name__, value.__defaults__, tuple(cells)
        )
        result.__kwdefaults__ = value.__kwdefaults__
        functools.update_wrapper(result, value)
        return result
    if isinstance(value, (classmethod, staticmethod)):
        return type(value)(_rebind(value.__func__, old_cls, new_cls))
    if isinstance(value, property):
        return property(
            *(_rebind(f, old_cls, new_cls) for f in (value.fget, value.fset, value.fdel)),
            doc=value.__doc__,
        )
    return value


def rebuild_class(cls, annotations, properties, storage_slots, slots_enabled):
    namespace = dict(vars(cls))
    namespace.pop("__dict__", None)
    namespace.pop("__weakref__", None)
    for name, value in list(namespace.items()):
        if isinstance(value, types.MemberDescriptorType):
            namespace.pop(name)
    if slots_enabled or "__slots__" in cls.__dict__:
        inherited_slots = {name for base in cls.__mro__[1:] for name in slot_names(base)}
        own_slots = list(slot_names(cls))
        if slots_enabled:
            own_slots.extend(annotations)
        own_slots = [n for n in own_slots if n not in properties and n not in inherited_slots]
        own_slots.extend(n for n in storage_slots if n not in inherited_slots)
        namespace["__slots__"] = tuple(dict.fromkeys(own_slots))
        for name in namespace["__slots__"]:
            namespace.pop(name, None)
    namespace.update(properties)
    result = type(cls)(cls.__name__, cls.__bases__, namespace)
    for name, value in namespace.items():
        rebound = _rebind(value, cls, result)
        if rebound is not value:
            setattr(result, name, rebound)
    return result


def instance_state(obj):
    """Read actual storage, avoiding public properties and omitted ancestor slots."""
    state = dict(getattr(obj, "__dict__", {}))
    for base in type(obj).__mro__:
        for name, descriptor in vars(base).items():
            if isinstance(descriptor, types.MemberDescriptorType):
                try:
                    state[name] = descriptor.__get__(obj, type(obj))
                except AttributeError:
                    pass
    return state


def restore_state(obj, state):
    for name, value in state.items():
        object.__setattr__(obj, name, value)


def copy_instance(obj):
    """Shallow copy user values but keep packed primitive storage independent."""
    result = object.__new__(type(obj))
    state = instance_state(obj)
    if "__compact_buffer__" in state:
        state["__compact_buffer__"] = state["__compact_buffer__"].copy()
    restore_state(result, state)
    return result
