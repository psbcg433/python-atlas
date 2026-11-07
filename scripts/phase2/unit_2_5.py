"""Unit 2.5 — Attribute Access, Descriptors and Metaprogramming (with Lab 2.5)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import annotationlib
import copy
import dataclasses
import enum
import functools
import importlib.util
import inspect
import sqlite3
import sys
import timeit
import tracemalloc
import types
import weakref
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


def set_attribute(target: object, attribute_name: str, value: object) -> None:
    """`target.attribute_name = value` as a call, for use inside raised_error_name(lambda: ...)."""
    setattr(target, attribute_name, value)


def mro_names(cls: type) -> list[str]:
    """Class names along cls.__mro__."""
    return [klass.__name__ for klass in cls.__mro__]


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 2.5 — Attribute Access, Descriptors and Metaprogramming

            **Objectives**

            - Trace exactly what `obj.name` does: data descriptors, the instance `__dict__`,
              non-data descriptors and class attributes, then `__getattr__`.
            - Hook attribute access with `__getattr__`, `__getattribute__`, `__setattr__` and
              `__delattr__` without falling into recursion traps.
            - Write descriptors (`__get__`, `__set__`, `__delete__`, `__set_name__`), and see
              that methods, `property`, `classmethod` and `staticmethod` are descriptors.
            - Use `__slots__` and measure what it saves.
            - Create classes at run time with `type(...)`, write metaclasses, and prefer the
              lighter `__init_subclass__` and class decorators when they are enough.
            - Recognize these mechanisms inside Pydantic, SQLAlchemy, Django and dataclasses.

            **JS bridge**

            | JavaScript | Python | The difference that bites |
            | --- | --- | --- |
            | Prototype chain lookup | MRO lookup + the descriptor protocol | A class attribute can **intercept** instance access (`__get__`) |
            | `Object.defineProperty(obj, "x", {get, set})` | a descriptor object on the class | Defined once on the class, reused by every attribute that needs it |
            | `Proxy` with `get` / `set` traps | `__getattr__`, `__getattribute__`, `__setattr__` | `__getattr__` runs only for **missing** names |
            | `Object.freeze` / sealed objects | `__slots__` (no new attributes), read-only descriptors | Slots are mainly a memory feature |
            | `class` expressions, `Function` constructor | `type(name, bases, namespace)` | Classes are ordinary objects created by calling their metaclass |
            | No metaclasses (decorators proposal is the nearest) | `metaclass=` / `__init_subclass__` | Code that runs when a **class** is defined |
            | `this` binding with `.bind` | functions are descriptors: `function.__get__` makes bound methods | Binding happens on attribute access, automatically |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _lookup_cells() -> list[NotebookNode]:
    """2.5.1 The attribute-lookup algorithm."""
    return [
        md(
            """
            ### 2.5.1 The attribute-lookup algorithm

            Reading `obj.name` calls `type(obj).__getattribute__(obj, "name")`. For ordinary
            classes that is `object.__getattribute__`, which follows this order:

            1. Search `type(obj).__mro__` for `name`. If found and it is a **data descriptor**
               (its type defines `__set__` or `__delete__`, like `property`), call its
               `__get__(obj, type(obj))` and stop.
            2. Otherwise, if `name` is in `obj.__dict__`, return that value.
            3. Otherwise, if the class attribute from step 1 is a **non-data descriptor**
               (only `__get__`, like a function), call its `__get__`; if it is a plain class
               attribute, return it as is.
            4. Otherwise raise `AttributeError`, and if the class defines `__getattr__`, call it
               instead of raising.

            ```mermaid
            flowchart TD
                A["obj.name"] --> B{"name found on type(obj).__mro__?"}
                B -- "yes, data descriptor" --> C["descriptor.__get__(obj, type)"]
                B -- "no, or not a data descriptor" --> D{"name in obj.__dict__?"}
                D -- yes --> E["return obj.__dict__[name]"]
                D -- no --> F{"class attribute found?"}
                F -- "non-data descriptor" --> G["descriptor.__get__(obj, type)"]
                F -- "plain attribute" --> H["return class attribute"]
                F -- no --> I{"__getattr__ defined?"}
                I -- yes --> J["type(obj).__getattr__(obj, name)"]
                I -- no --> K["raise AttributeError"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            obj.name
              |
              +-- found on type(obj).__mro__ AND is a data descriptor? --> descriptor.__get__(obj, type)
              |
              +-- name in obj.__dict__? -----------------------------> obj.__dict__[name]
              |
              +-- found on the class?
              |      non-data descriptor (has only __get__) ---------> descriptor.__get__(obj, type)
              |      plain attribute ---------------------------------> the attribute itself
              |
              +-- __getattr__ defined? -------------------------------> type(obj).__getattr__(obj, name)
              |
              +-- AttributeError
            ```

            </details>

            The class below has one attribute of each kind, plus `__getattr__`.
            """
        ),
        code(
            '''
            class Product:
                """One attribute of every kind."""

                category = "stationery"  # plain class attribute

                def __init__(self, name: str) -> None:
                    self.name = name  # instance attribute

                @property
                def label(self) -> str:  # data descriptor
                    return f"[{self.name}]"

                def describe(self) -> str:  # function: non-data descriptor
                    return f"{self.name} in {self.category}"

                def __getattr__(self, attribute_name: str) -> str:  # last resort
                    return f"<no {attribute_name}>"


            pen = Product("pen")
            for attribute_name in ["label", "name", "describe", "category", "colour"]:
                value = getattr(pen, attribute_name)
                shown = f"bound method {value.__qualname__}" if inspect.ismethod(value) else repr(value)
                print(f"{attribute_name:<9} -> {shown}")
            '''
        ),
        md(
            """
            **Precedence in action.** Write the same names straight into `pen.__dict__` (to
            bypass any setter). The data descriptor `label` still wins over the instance
            dictionary; the method and the class attribute are **shadowed** by it.
            """
        ),
        code(
            """
            vars(pen).update(label="shadow label", describe="shadow describe", category="shadow category")
            print(f"{pen.label=}  (data descriptor beats the instance dict)")
            print(f"{pen.describe=}  (instance dict beats a non-data descriptor)")
            print(f"{pen.category=}  (instance dict beats a plain class attribute)")
            print(f"{Product.category=}  (the class itself is unchanged)")
            """
        ),
        md(
            """
            #### Under the hood: the algorithm in Python

            A simplified `find_attribute` that follows the four steps (it ignores metaclasses
            and `__getattribute__` overrides). `inspect.getattr_static` does a similar
            descriptor-free lookup and is useful for debugging, because it never runs your
            code.
            """
        ),
        code(
            '''
            def find_attribute(obj: object, attribute_name: str) -> object:
                """Simplified object.__getattribute__ followed by the __getattr__ fallback."""
                class_attribute, found_on_class = None, False
                for klass in type(obj).__mro__:
                    if attribute_name in vars(klass):
                        class_attribute, found_on_class = vars(klass)[attribute_name], True
                        break
                descriptor_type = type(class_attribute)
                if found_on_class and (
                    hasattr(descriptor_type, "__set__") or hasattr(descriptor_type, "__delete__")
                ):
                    return descriptor_type.__get__(class_attribute, obj, type(obj))
                if attribute_name in getattr(obj, "__dict__", {}):
                    return obj.__dict__[attribute_name]
                if found_on_class and hasattr(descriptor_type, "__get__"):
                    return descriptor_type.__get__(class_attribute, obj, type(obj))
                if found_on_class:
                    return class_attribute
                if hasattr(type(obj), "__getattr__"):
                    return type(obj).__getattr__(obj, attribute_name)
                raise AttributeError(attribute_name)


            fresh_pen = Product("pen")
            for attribute_name in ["label", "name", "category", "colour"]:
                same_answer = find_attribute(fresh_pen, attribute_name) == getattr(fresh_pen, attribute_name)
                print(f"{attribute_name:<9} same as getattr: {same_answer}")
            print(f"{find_attribute(fresh_pen, 'describe')()=}")
            print(
                f"{type(inspect.getattr_static(fresh_pen, 'label')).__name__=}  (the descriptor, not its value)"
            )
            '''
        ),
    ]


def _hook_cells() -> list[NotebookNode]:
    """2.5.2 Attribute hooks."""
    return [
        md(
            """
            ### 2.5.2 Attribute hooks

            | Hook | Runs | Typical use |
            | --- | --- | --- |
            | `__getattr__(self, name)` | only when normal lookup **fails** | defaults, delegation, lazy loading |
            | `__getattribute__(self, name)` | on **every** attribute read | tracing, access control (rarely needed) |
            | `__setattr__(self, name, value)` | on every assignment `obj.name = value` | validation, freezing, change tracking |
            | `__delattr__(self, name)` | on every `del obj.name` | protecting required attributes |

            **`__getattr__`** is the safe one: real attributes never reach it. This settings
            object answers from a defaults table for anything not set explicitly.
            """
        ),
        code(
            '''
            class Settings:
                """Explicit values win; anything else comes from DEFAULTS."""

                DEFAULTS = {"timeout_seconds": 30, "retries": 3}

                def __init__(self, **overrides: object) -> None:
                    self.__dict__.update(overrides)

                def __getattr__(self, setting_name: str) -> object:
                    try:
                        return self.DEFAULTS[setting_name]
                    except KeyError:
                        raise AttributeError(f"unknown setting {setting_name!r}") from None


            app_settings = Settings(timeout_seconds=5)
            print(f"{app_settings.timeout_seconds=}, {app_settings.retries=}")
            print(raised_message(lambda: app_settings.colour))
            print(f"{hasattr(app_settings, 'colour')=}  (hasattr relies on AttributeError)")
            '''
        ),
        md(
            """
            **`__getattribute__`** intercepts every read, including `self.__dict__` and method
            lookups. It must delegate to `super().__getattribute__(name)` (or
            `object.__getattribute__`) to do the real work.
            """
        ),
        code(
            '''
            class AccessCounter:
                """Counts every attribute read."""

                def __init__(self, sku: str) -> None:
                    self.sku = sku
                    self.reads: dict[str, int] = {}

                def __getattribute__(self, attribute_name: str) -> Any:
                    reads = super().__getattribute__("reads")
                    reads[attribute_name] = reads.get(attribute_name, 0) + 1
                    return super().__getattribute__(attribute_name)


            counted = AccessCounter("PEN-01")
            _ = counted.sku, counted.sku, counted.__class__
            print(f"{object.__getattribute__(counted, 'reads')=}")
            '''
        ),
        md(
            """
            #### Recursion traps

            Inside these hooks, `self.anything` goes through the hook again. Reading
            `self.reads` inside `__getattribute__`, or assigning `self.x = ...` inside
            `__setattr__`, recurses until `RecursionError`. Always go through `super()` (or
            `object`) for the real access.
            """
        ),
        code(
            """
            class RecursiveGetter:
                def __getattribute__(self, attribute_name: str) -> Any:
                    return self.__dict__[attribute_name]  # self.__dict__ calls this method again


            class RecursiveSetter:
                def __setattr__(self, attribute_name: str, value: object) -> None:
                    self.attribute_name = value  # assignment calls this method again


            print(raised_error_name(lambda: RecursiveGetter().anything))
            print(raised_error_name(lambda: set_attribute(RecursiveSetter(), "x", 1)))
            """
        ),
        md(
            """
            A subtler trap: `__getattr__` that reads an attribute set in `__init__`. `copy`,
            `pickle` and some frameworks create instances **without calling `__init__`**, so
            `self._target` does not exist yet, which calls `__getattr__("_target")`, which reads
            `self._target` again... The fix is to refuse private names before delegating.
            """
        ),
        code(
            """
            class NaiveProxy:
                def __init__(self, target: object) -> None:
                    self._target = target

                def __getattr__(self, attribute_name: str) -> Any:
                    return getattr(self._target, attribute_name)


            class SafeProxy(NaiveProxy):
                def __getattr__(self, attribute_name: str) -> Any:
                    if attribute_name.startswith("_"):
                        raise AttributeError(attribute_name)
                    return getattr(self._target, attribute_name)


            print(raised_error_name(lambda: copy.copy(NaiveProxy([1, 2]))))
            print(f"{copy.copy(SafeProxy([1, 2])).count(2)=}")
            """
        ),
        md(
            """
            **`__setattr__`** sees every assignment, including those in `__init__`. This class
            validates while it is being built and refuses changes afterwards ("frozen after
            init"); `object.__setattr__` is the escape hatch it uses itself.
            """
        ),
        code(
            '''
            class ShippingLabel:
                """Validated on creation, read-only afterwards."""

                def __init__(self, tracking_number: str, weight_kg: float) -> None:
                    self.tracking_number = tracking_number
                    self.weight_kg = weight_kg
                    object.__setattr__(self, "_frozen", True)

                def __setattr__(self, attribute_name: str, value: object) -> None:
                    if getattr(self, "_frozen", False):
                        raise AttributeError(f"ShippingLabel is read-only (tried to set {attribute_name})")
                    if attribute_name == "weight_kg" and not 0 < value <= 30:  # type: ignore[operator]
                        raise ValueError("weight_kg must be in (0, 30]")
                    super().__setattr__(attribute_name, value)


            label = ShippingLabel("BD123456789IN", 2.5)
            print(raised_message(lambda: set_attribute(label, "weight_kg", 3)))
            print(raised_message(lambda: ShippingLabel("BD1", 45)))
            '''
        ),
        md(
            """
            **`__delattr__`** handles `del obj.name`. Here required fields cannot be deleted,
            optional ones can.
            """
        ),
        code(
            """
            class CustomerRecord:
                REQUIRED = frozenset({"customer_id", "email"})

                def __init__(self, customer_id: int, email: str, nickname: str) -> None:
                    self.customer_id, self.email, self.nickname = customer_id, email, nickname

                def __delattr__(self, attribute_name: str) -> None:
                    if attribute_name in self.REQUIRED:
                        raise AttributeError(f"{attribute_name} is required and cannot be deleted")
                    super().__delattr__(attribute_name)


            record = CustomerRecord(7, "asha@example.com", "ash")
            del record.nickname
            print(f"{vars(record)=}")
            print(raised_message(lambda: record.__delattr__("email")))
            """
        ),
        md(
            """
            #### Proxies

            A **proxy** stands in for another object. `__getattr__` forwards every *missing*
            attribute, so the proxy only defines what it changes. This read-only proxy forwards
            reads and blocks writes. Note the limit from Unit 2.4.9: implicit special-method
            calls such as `len(proxy)` look on the **type**, so `__getattr__` never sees them;
            each dunder you need must be written on the proxy class.
            """
        ),
        code(
            '''
            class ReadOnlyProxy:
                """Forwards reads to the target; refuses writes."""

                def __init__(self, target: object) -> None:
                    object.__setattr__(self, "_target", target)

                def __getattr__(self, attribute_name: str) -> Any:
                    if attribute_name == "_target":  # not set yet (copy, pickle): avoid recursion
                        raise AttributeError(attribute_name)
                    return getattr(self._target, attribute_name)

                def __setattr__(self, attribute_name: str, value: object) -> None:
                    raise AttributeError(f"read-only proxy: cannot set {attribute_name}")


            settings_view = ReadOnlyProxy(Settings(timeout_seconds=5))
            print(f"{settings_view.timeout_seconds=}, {settings_view.retries=}")
            print(raised_message(lambda: set_attribute(settings_view, "retries", 10)))
            print(raised_message(lambda: len(ReadOnlyProxy([1, 2, 3]))))
            print(f"{ReadOnlyProxy([1, 2, 3]).__len__()=}  (explicit call goes through __getattr__)")
            '''
        ),
        md(
            """
            #### Lazy loading

            `__getattr__` also suits **lazy loading**: fetch expensive data on first use, then
            store it in the instance `__dict__` so later reads never reach `__getattr__` again.
            ORMs load related rows this way. The fake database counts its queries.
            """
        ),
        code(
            '''
            QUERY_LOG: list[str] = []


            def fetch_customer_row(customer_id: int) -> dict[str, object]:
                """Pretend database query."""
                QUERY_LOG.append(f"SELECT * FROM customers WHERE id = {customer_id}")
                return {"name": "Asha Rao", "city": "Pune", "orders": 12}


            class LazyCustomer:
                """Only the id is known until a column is read."""

                def __init__(self, customer_id: int) -> None:
                    self.customer_id = customer_id

                def __getattr__(self, column: str) -> object:
                    if column.startswith("_"):
                        raise AttributeError(column)
                    row = fetch_customer_row(self.customer_id)
                    self.__dict__.update(row)  # cache every column at once
                    if column not in row:
                        raise AttributeError(column)
                    return row[column]


            customer = LazyCustomer(42)
            print(f"{len(QUERY_LOG)=} after creation")
            print(f"{customer.name=}, {customer.city=}, {customer.orders=}")
            print(f"{len(QUERY_LOG)=} after three reads")
            '''
        ),
    ]


def _descriptor_cells() -> list[NotebookNode]:
    """2.5.3 The descriptor protocol."""
    return [
        md(
            """
            ### 2.5.3 The descriptor protocol

            A **descriptor** is an object, stored as a **class** attribute, whose type defines
            any of these methods. It takes over access to that attribute on every instance.

            | Method | Called for | Arguments |
            | --- | --- | --- |
            | `__get__(self, instance, owner)` | `instance.attr` and `Owner.attr` | `instance` is `None` for class access |
            | `__set__(self, instance, value)` | `instance.attr = value` | |
            | `__delete__(self, instance)` | `del instance.attr` | |
            | `__set_name__(self, owner, name)` | once, when the owning class is created | lets the descriptor learn its attribute name |

            A **data descriptor** defines `__set__` or `__delete__` and beats the instance
            `__dict__`; a **non-data descriptor** defines only `__get__` and loses to it
            (2.5.1). The tracer below prints each call.
            """
        ),
        code(
            '''
            class Traced:
                """Prints every descriptor call; stores the value in the instance __dict__."""

                def __set_name__(self, owner: type, name: str) -> None:
                    print(f"  __set_name__(owner={owner.__name__}, name={name!r})")
                    self.name = name

                def __get__(self, instance: object, owner: type | None = None) -> object:
                    print(f"  __get__(instance={type(instance).__name__}, owner={owner.__name__})")
                    if instance is None:
                        return self  # class access returns the descriptor itself
                    return instance.__dict__[self.name]

                def __set__(self, instance: object, value: object) -> None:
                    print(f"  __set__({value!r})")
                    instance.__dict__[self.name] = value

                def __delete__(self, instance: object) -> None:
                    print("  __delete__()")
                    del instance.__dict__[self.name]


            print("defining the class:")


            class Parcel:
                weight_kg = Traced()
            '''
        ),
        md(
            """
            `__set_name__` already ran when the class statement finished. Now each kind of
            access calls a different method; class access passes `instance=None`.
            """
        ),
        code(
            """
            parcel = Parcel()
            parcel.weight_kg = 2.5
            print(f"{parcel.weight_kg=}")
            del parcel.weight_kg
            print(f"{type(Parcel.weight_kg).__name__=}")
            """
        ),
        md(
            """
            `__set_name__` is called by `type.__new__` only for attributes present when the
            class is created. A descriptor attached later must be told its name by hand.
            """
        ),
        code(
            """
            late_descriptor = Traced()
            Parcel.length_cm = late_descriptor
            print(f"{hasattr(late_descriptor, 'name')=}")
            late_descriptor.__set_name__(Parcel, "length_cm")
            """
        ),
        md(
            """
            **Data vs non-data.** The same `__get__` behaves differently depending on whether a
            `__set__` exists. Without it, an instance attribute of the same name shadows the
            descriptor after the first assignment; with it, every access keeps going through
            the descriptor.
            """
        ),
        code(
            '''
            class Greeting:
                """Non-data descriptor: only __get__."""

                def __get__(self, instance: object, owner: type | None = None) -> str:
                    return "computed hello"


            class StrictGreeting(Greeting):
                """Data descriptor: adds __set__."""

                def __set__(self, instance: object, value: object) -> None:
                    raise AttributeError("greeting is read-only")


            class Page:
                greeting = Greeting()
                strict_greeting = StrictGreeting()


            page = Page()
            page.__dict__.update(greeting="from __dict__", strict_greeting="from __dict__")
            print(f"{page.greeting=}  (non-data: the instance dict wins)")
            print(f"{page.strict_greeting=}  (data: the descriptor wins)")
            for descriptor_name in ("greeting", "strict_greeting"):
                is_data = inspect.isdatadescriptor(vars(Page)[descriptor_name])
                print(f"{descriptor_name}: data descriptor? {is_data}")
            '''
        ),
        md(
            """
            #### A reusable `PositiveNumber` descriptor

            One descriptor class, many attributes: `__set_name__` tells each instance which
            name it manages, so error messages are precise. Values live in the instance's own
            `__dict__` under a private name (`_price`), so instances do not share state.
            """
        ),
        code(
            '''
            class PositiveNumber:
                """A numeric attribute that must stay greater than zero."""

                def __set_name__(self, owner: type, name: str) -> None:
                    self.public_name = name
                    self.storage_name = f"_{name}"

                def __get__(self, instance: object, owner: type | None = None) -> Any:
                    if instance is None:
                        return self
                    return getattr(instance, self.storage_name)

                def __set__(self, instance: object, value: object) -> None:
                    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
                        raise TypeError(f"{self.public_name} must be a number, got {type(value).__name__}")
                    if value <= 0:
                        raise ValueError(f"{self.public_name} must be > 0, got {value}")
                    setattr(instance, self.storage_name, value)


            class OrderLine:
                unit_price = PositiveNumber()
                quantity = PositiveNumber()

                def __init__(self, unit_price: Decimal, quantity: int) -> None:
                    self.unit_price = unit_price  # goes through PositiveNumber.__set__
                    self.quantity = quantity
            '''
        ),
        md(
            """
            Validation runs in `__init__` and on every later assignment, with no property
            boilerplate per attribute. The values sit in `vars(line)` under the storage names.
            """
        ),
        code(
            """
            line = OrderLine(Decimal("49.99"), 3)
            print(f"{line.unit_price=}, {line.quantity=}, {vars(line)=}")
            print(raised_message(lambda: OrderLine(Decimal("49.99"), 0)))
            print(raised_message(lambda: set_attribute(line, "unit_price", "free")))
            print(raised_message(lambda: set_attribute(line, "quantity", True)))
            """
        ),
        md(
            """
            > **Warning:** a descriptor is shared by **all** instances of the class. Storing the
            > value on `self` (the descriptor) instead of on `instance` makes every instance
            > see the last value written:
            """
        ),
        code(
            '''
            class SharedStateBug:
                """BUG: keeps the value on the descriptor."""

                def __get__(self, instance: object, owner: type | None = None) -> object:
                    return self.value

                def __set__(self, instance: object, value: object) -> None:
                    self.value = value


            class Account:
                balance = SharedStateBug()


            first_account, second_account = Account(), Account()
            first_account.balance = 100
            second_account.balance = 5
            print(f"{first_account.balance=}  (overwritten by second_account)")
            '''
        ),
    ]


def _builtin_descriptor_cells() -> list[NotebookNode]:
    """2.5.4 Descriptors inside Python."""
    return [
        md(
            """
            ### 2.5.4 Descriptors inside Python

            **Functions are non-data descriptors.** A `def` in a class body stores a plain
            function in the class `__dict__`. Every function has a `__get__`: called with an
            instance it returns a **bound method**, called with `None` it returns the function
            itself. That is all "method binding" is (Unit 2.1.4 previewed it).
            """
        ),
        code(
            """
            class Greeter:
                def greet(self, name: str) -> str:
                    return f"Hello, {name}"


            raw_function = vars(Greeter)["greet"]
            greeter = Greeter()
            print(f"{type(raw_function).__name__=}, {hasattr(raw_function, '__get__')=}")
            print(f"{type(raw_function.__get__(greeter, Greeter)).__name__=}")
            print(f"{raw_function.__get__(None, Greeter) is raw_function=}  (class access)")
            print(f"{raw_function.__get__(greeter, Greeter)('Asha')=}")
            """
        ),
        md(
            """
            Built-in methods use the C equivalent, `method_descriptor`. And because functions
            are non-data descriptors, an instance attribute can shadow a method (rarely a good
            idea, but it explains surprising bugs).
            """
        ),
        code(
            """
            upper_descriptor = vars(str)["upper"]
            print(f"{type(upper_descriptor).__name__=}")
            print(f"{upper_descriptor.__get__('chai', str)()=}")
            greeter.greet = lambda name: f"shadowed {name}"  # type: ignore[method-assign]
            print(f"{greeter.greet('Asha')=}, {Greeter().greet('Asha')=}")
            """
        ),
        md(
            """
            #### Rebuilding `property` (read-only)

            A minimal read-only property needs `__get__` **and** a `__set__` that refuses.
            Without `__set__` it would be a non-data descriptor, and an assignment would quietly
            create an instance attribute that hides it. Lab 2.5 builds the full version with
            setters and deleters.
            """
        ),
        code(
            '''
            class ReadOnlyProperty:
                """property(fget) with no setter, rebuilt."""

                def __init__(self, fget: Callable[[Any], Any]) -> None:
                    self.fget = fget
                    self.__doc__ = fget.__doc__

                def __set_name__(self, owner: type, name: str) -> None:
                    self.name = name

                def __get__(self, instance: object, owner: type | None = None) -> Any:
                    if instance is None:
                        return self
                    return self.fget(instance)

                def __set__(self, instance: object, value: object) -> None:
                    raise AttributeError(f"property {self.name!r} is read-only")


            class Circle:
                def __init__(self, radius: float) -> None:
                    self.radius = radius

                @ReadOnlyProperty
                def diameter(self) -> float:
                    """Twice the radius."""
                    return self.radius * 2


            wheel = Circle(30)
            print(f"{wheel.diameter=}, {Circle.diameter.__doc__=}")
            print(raised_message(lambda: set_attribute(wheel, "diameter", 1)))
            '''
        ),
        md(
            """
            #### Rebuilding `classmethod` and `staticmethod`

            `classmethod.__get__` binds the function to the **class** (`types.MethodType(func,
            owner)`); `staticmethod.__get__` returns the function unchanged. Both are non-data
            descriptors of a few lines each.
            """
        ),
        code(
            """
            class MyClassMethod:
                def __init__(self, func: Callable[..., Any]) -> None:
                    self.func = func

                def __get__(self, instance: object, owner: type | None = None) -> Any:
                    owner = owner if owner is not None else type(instance)
                    return types.MethodType(self.func, owner)


            class MyStaticMethod:
                def __init__(self, func: Callable[..., Any]) -> None:
                    self.func = func

                def __get__(self, instance: object, owner: type | None = None) -> Any:
                    return self.func
            """
        ),
        md(
            """
            They behave like the built-ins, including on subclasses: the class method receives
            the subclass it was called on.
            """
        ),
        code(
            """
            class Temperature:
                def __init__(self, celsius: float) -> None:
                    self.celsius = celsius

                @MyClassMethod
                def from_fahrenheit(cls, fahrenheit: float) -> Any:
                    return cls(round((fahrenheit - 32) * 5 / 9, 1))

                @MyStaticMethod
                def is_freezing(celsius: float) -> bool:
                    return celsius <= 0


            class OvenTemperature(Temperature):
                pass


            hot_oven = OvenTemperature.from_fahrenheit(392)
            print(f"{type(hot_oven).__name__=}, {hot_oven.celsius=}")
            print(f"{Temperature.is_freezing(-3)=}, {Temperature(5).is_freezing(5)=}")
            print(f"{type(vars(Temperature)['from_fahrenheit']).__name__=}")
            """
        ),
    ]


def _slots_cells() -> list[NotebookNode]:
    """2.5.5 __slots__."""
    return [
        md(
            """
            ### 2.5.5 `__slots__`

            `__slots__ = ("x", "y")` tells Python to reserve fixed storage for those names in
            each instance and to give instances **no `__dict__`**. Each slot becomes a
            `member_descriptor` (a data descriptor) on the class. Assigning any other name
            fails.
            """
        ),
        code(
            """
            class PointWithDict:
                def __init__(self, x: int, y: int) -> None:
                    self.x, self.y = x, y


            class SlottedPoint:
                __slots__ = ("x", "y")

                def __init__(self, x: int, y: int) -> None:
                    self.x, self.y = x, y


            slotted = SlottedPoint(1, 2)
            print(f"{hasattr(PointWithDict(1, 2), '__dict__')=}, {hasattr(slotted, '__dict__')=}")
            slot_descriptor = vars(SlottedPoint)["x"]
            print(f"{type(slot_descriptor).__name__=}, {inspect.isdatadescriptor(slot_descriptor)=}")
            print(raised_message(lambda: set_attribute(slotted, "z", 3)))
            """
        ),
        md(
            """
            #### Memory on 1M instances

            `tracemalloc` measures one million instances of each class (the list holding them
            and the small ints are included in both figures). Since Python 3.11 ordinary
            instances share their key table and, since 3.13, store values inline until someone
            asks for `__dict__`, so the gap is smaller than older articles claim. It is still
            real: roughly 40 bytes per instance here. Takes about 2 seconds; figures vary by
            version and platform.
            """
        ),
        code(
            '''
            INSTANCE_COUNT = 1_000_000


            def traced_bytes(point_class: type) -> int:
                """Traced memory in bytes while INSTANCE_COUNT instances are alive."""
                tracemalloc.start()
                points = [point_class(number, number) for number in range(INSTANCE_COUNT)]
                current_bytes, _peak_bytes = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                del points
                return current_bytes


            dict_bytes = traced_bytes(PointWithDict)
            slots_bytes = traced_bytes(SlottedPoint)
            print(f"__dict__ instances:  {dict_bytes / 1e6:6.1f} MB")
            print(f"__slots__ instances: {slots_bytes / 1e6:6.1f} MB")
            print(f"saved per instance:  {(dict_bytes - slots_bytes) / INSTANCE_COUNT:.0f} bytes")
            '''
        ),
        md(
            """
            #### Speed

            Attribute reads through a slot and through an inline-values `__dict__` take about
            the same time on 3.15 (the specializing interpreter, Unit 1.1, handles both). Slots
            mainly buy **memory** and a fixed set of attributes, not speed.
            """
        ),
        code(
            """
            dict_point, slot_point = PointWithDict(1, 2), SlottedPoint(1, 2)
            read_dict = min(timeit.repeat("point.x", globals={"point": dict_point}, number=1_000_000, repeat=5))
            read_slot = min(timeit.repeat("point.x", globals={"point": slot_point}, number=1_000_000, repeat=5))
            print(f"read via __dict__: {read_dict * 1_000:.1f} ns per read")
            print(f"read via slot:     {read_slot * 1_000:.1f} ns per read")
            """
        ),
        md(
            """
            #### Trade-offs

            | Trade-off | Detail |
            | --- | --- |
            | No new attributes | good for value objects, bad for monkey-patching and some mocking |
            | Subclasses get a `__dict__` back | unless they declare `__slots__` too (even `()`) |
            | No weak references | unless `"__weakref__"` is in the slots |
            | No class attribute with a slot's name | it would replace the slot descriptor (`ValueError`) |
            | `functools.cached_property` needs `__dict__` | it stores the value there (`TypeError` with slots) |
            | Multiple inheritance | two bases with non-empty slots cannot be combined (layout conflict) |
            | Simplest route | `@dataclass(slots=True)` (Unit 2.6) writes the slots for you |

            The first four rows, demonstrated:
            """
        ),
        code(
            """
            class LabelledPoint(SlottedPoint):  # forgot __slots__
                pass


            print(f"{hasattr(LabelledPoint(1, 2), '__dict__')=}  (the subclass brought it back)")
            print(raised_message(lambda: weakref.ref(slotted)))


            def class_with_conflict() -> type:
                class Conflicting:
                    __slots__ = ("x",)
                    x = 0  # a default value would overwrite the slot descriptor

                return Conflicting


            print(raised_message(class_with_conflict))
            """
        ),
        md(
            """
            The last two rows: `cached_property` cannot store its result, and two slotted bases
            cannot share one instance layout.
            """
        ),
        code(
            """
            class SlottedReport:
                __slots__ = ("rows",)

                def __init__(self, rows: list[int]) -> None:
                    self.rows = rows

                @functools.cached_property
                def total(self) -> int:
                    return sum(self.rows)


            def combine_slotted_bases() -> type:
                class WithX:
                    __slots__ = ("x",)

                class WithY:
                    __slots__ = ("y",)

                class WithBoth(WithX, WithY):
                    pass

                return WithBoth


            print(raised_error_name(lambda: SlottedReport([1, 2]).total))
            print(raised_message(combine_slotted_bases))
            """
        ),
    ]


def _classes_as_objects_cells() -> list[NotebookNode]:
    """2.5.6 Classes as objects."""
    return [
        md(
            """
            ### 2.5.6 Classes as objects

            A class is an ordinary object: you can pass it to functions, store it in a dict and
            add attributes to it. Its type is its **metaclass**, which for normal classes is
            `type` (and `type` is its own type).
            """
        ),
        code(
            """
            class Invoice:
                pass


            exporters = {"invoice": Invoice}
            print(f"{type(Invoice)=}, {type(type)=}, {isinstance(Invoice, type)=}")
            print(f"{exporters['invoice']().__class__.__name__=}")
            Invoice.currency = "INR"  # classes are mutable objects
            print(f"{Invoice().currency=}")
            """
        ),
        md(
            """
            **`type(name, bases, namespace)`** creates a class directly; a `class` statement is
            mostly syntax for this call. The namespace dict becomes the class `__dict__`, so
            functions in it become methods.
            """
        ),
        code(
            """
            def describe_coupon(self: Any) -> str:
                return f"{self.code}: {self.percent}% off"


            Coupon = type(
                "Coupon",
                (object,),
                {"percent": 10, "code": "WELCOME", "describe": describe_coupon, "__doc__": "A discount code."},
            )
            print(f"{Coupon.__name__=}, {Coupon.__doc__=}, {Coupon().describe()=}")
            print(f"{mro_names(Coupon)=}")
            """
        ),
        md(
            """
            **Dynamic class creation.** Building classes from data is useful when the shape is
            only known at run time, for example from a configuration file or an API schema. This
            factory makes small record classes with a generated `__init__` and `__repr__`.
            `collections.namedtuple` (Unit 1.5.6) and `dataclasses.make_dataclass` work the same
            way.
            """
        ),
        code(
            '''
            def make_record_class(class_name: str, field_names: list[str]) -> type:
                """Build a class with an __init__ taking field_names, and a matching __repr__."""

                def __init__(self: Any, *values: object) -> None:
                    if len(values) != len(field_names):
                        raise TypeError(f"{class_name} takes {len(field_names)} values, got {len(values)}")
                    for field_name, value in zip(field_names, values, strict=True):
                        setattr(self, field_name, value)

                def __repr__(self: Any) -> str:
                    pairs = ", ".join(f"{name}={getattr(self, name)!r}" for name in field_names)
                    return f"{class_name}({pairs})"

                return type(
                    class_name, (), {"__init__": __init__, "__repr__": __repr__, "fields": tuple(field_names)}
                )


            schema = {"Shipment": ["tracking_number", "courier"], "Refund": ["order_id", "amount"]}
            generated = {name: make_record_class(name, fields) for name, fields in schema.items()}
            print(generated["Shipment"]("BD123", "BlueDart"))
            print(generated["Refund"]("ORD-7", Decimal("250.00")))
            print(raised_message(lambda: generated["Refund"]("ORD-7")))
            '''
        ),
        md(
            """
            `types.new_class` is the full equivalent of a `class` statement, including class
            keywords such as `metaclass=` (which the three-argument `type()` cannot take) and a
            callback that fills the namespace.
            """
        ),
        code(
            """
            def fill_namespace(namespace: dict[str, Any]) -> None:
                @abstractmethod
                def export(self: Any) -> str: ...

                namespace["export"] = export


            Exporter = types.new_class("Exporter", (), {"metaclass": ABCMeta}, fill_namespace)
            print(f"{type(Exporter).__name__=}, {sorted(Exporter.__abstractmethods__)=}")
            print(raised_error_name(Exporter))
            """
        ),
    ]


def _metaclass_cells() -> list[NotebookNode]:
    """2.5.7 Metaclasses."""
    return [
        md(
            """
            ### 2.5.7 Metaclasses

            A **metaclass** is the class of a class. Subclass `type` and its methods run when
            classes are **created** and when they are **called**:

            | Metaclass method | Runs when | Use it to |
            | --- | --- | --- |
            | `__prepare__(name, bases, **kwargs)` | before the class body executes | supply the namespace object the body writes into |
            | `__new__(mcls, name, bases, namespace)` | after the body, to build the class | inspect or change the namespace, return the class |
            | `__init__(cls, name, bases, namespace)` | after `__new__` | register or validate the finished class |
            | `__call__(cls, *args, **kwargs)` | when the class is called, `MyClass(...)` | control instance creation (singletons, caching) |

            The trace shows the full order of a class statement, including the hooks from 2.5.3
            and 2.5.8 (`__set_name__`, `__init_subclass__`) and a class decorator.
            """
        ),
        code(
            """
            class TracingMeta(type):
                @classmethod
                def __prepare__(mcls, name: str, bases: tuple[type, ...], **kwargs: Any) -> dict[str, Any]:
                    print(f"1. {mcls.__name__}.__prepare__({name!r})")
                    return {}

                def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
                    body_names = [key for key in namespace if not key.startswith("__")]
                    print(f"3. {mcls.__name__}.__new__ with body names {body_names}")
                    return super().__new__(mcls, name, bases, namespace)

                def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> None:
                    print(f"6. {type(cls).__name__}.__init__({name!r})")
                    super().__init__(name, bases, namespace)


            class Announcer:
                def __set_name__(self, owner: type, name: str) -> None:
                    print(f"4. __set_name__({name!r}) inside type.__new__")


            class TracedBase(metaclass=TracingMeta):
                def __init_subclass__(cls, **kwargs: Any) -> None:
                    print(f"5. __init_subclass__({cls.__name__!r}) inside type.__new__")
                    super().__init_subclass__(**kwargs)


            def class_decorator(cls: type) -> type:
                print(f"7. class decorator gets the finished {cls.__name__!r}")
                return cls
            """
        ),
        md(
            """
            Defining `TracedBase` already ran steps 1, 3 and 6 for the base itself
            (`__init_subclass__` only runs for subclasses). Now a decorated subclass with a
            descriptor in its body shows every step in order:
            """
        ),
        code(
            """
            @class_decorator
            class Report(TracedBase):
                print("2. class body executes")
                title = Announcer()
            """
        ),
        md(
            """
            #### `__new__`: shape the class

            `__new__` receives the namespace before the class exists, so it can add, rename or
            reject entries. This metaclass derives a `table_name` for every model class that
            does not set one, the kind of convention Django and SQLAlchemy apply.
            """
        ),
        code(
            """
            class TableNameMeta(type):
                def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
                    namespace.setdefault("table_name", name.lower() + "s")
                    return super().__new__(mcls, name, bases, namespace)


            class Record(metaclass=TableNameMeta):
                pass


            class Customer(Record):
                pass


            class Person(Record):
                table_name = "people"


            print(f"{Customer.table_name=}, {Person.table_name=}, {type(Customer).__name__=}")
            """
        ),
        md(
            """
            #### `__init__` and registries

            The metaclass `__init__` runs for every class created with it, **including
            subclasses**, which makes it a natural place for a registry. Skipping the base class
            keeps it out.
            """
        ),
        code(
            """
            class RegistryMeta(type):
                registry: dict[str, type] = {}

                def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> None:
                    super().__init__(name, bases, namespace)
                    if bases:  # not the base class itself
                        RegistryMeta.registry[name.removesuffix("Notifier").lower()] = cls


            class Notifier(metaclass=RegistryMeta):
                pass


            class EmailNotifier(Notifier):
                pass


            class SmsNotifier(Notifier):
                pass


            print(f"{RegistryMeta.registry=}")
            print(f"{RegistryMeta.registry['sms']().__class__.__name__=}")
            """
        ),
        md(
            """
            #### Interface enforcement

            An ABC complains when you **instantiate** an incomplete class (Unit 2.3.1); a
            metaclass can complain when the class is **defined**, which surfaces mistakes at
            import time.
            """
        ),
        code(
            """
            class InterfaceMeta(type):
                required_methods = ("load", "save")

                def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
                    cls = super().__new__(mcls, name, bases, namespace)
                    if bases:
                        missing = [
                            method
                            for method in mcls.required_methods
                            if not callable(getattr(cls, method, None))
                        ]
                        if missing:
                            raise TypeError(f"{name} must define {', '.join(missing)}")
                    return cls


            class StorageBackend(metaclass=InterfaceMeta):
                pass


            def define_incomplete_backend() -> type:
                class DiskBackend(StorageBackend):
                    def load(self) -> bytes:
                        return b""

                return DiskBackend


            print(raised_message(define_incomplete_backend))
            """
        ),
        md(
            """
            #### `__call__` and singletons

            `MyClass(...)` is a call on the class, so it runs `type(MyClass).__call__`, which
            normally calls `__new__` and `__init__`. Overriding it controls instance creation:
            here the first instance is cached and returned every time. (2.6.5 shows why a
            module-level instance is usually the more Pythonic singleton.)
            """
        ),
        code(
            """
            class SingletonMeta(type):
                _instances: dict[type, object] = {}

                def __call__(cls, *args: Any, **kwargs: Any) -> Any:
                    if cls not in SingletonMeta._instances:
                        print(f"  creating the one {cls.__name__}")
                        SingletonMeta._instances[cls] = super().__call__(*args, **kwargs)
                    return SingletonMeta._instances[cls]


            class AppConfig(metaclass=SingletonMeta):
                def __init__(self, environment: str = "dev") -> None:
                    self.environment = environment


            first_config = AppConfig("prod")
            second_config = AppConfig("test")  # arguments ignored: already created
            print(f"{first_config is second_config=}, {second_config.environment=}")
            """
        ),
        md(
            """
            #### `__prepare__`: a custom namespace

            `__prepare__` returns the mapping that the class body writes into. A dict subclass
            that refuses duplicate names catches an easy mistake: defining the same method twice,
            where the second silently replaces the first.
            """
        ),
        code(
            """
            class NoDuplicatesNamespace(dict[str, Any]):
                def __setitem__(self, key: str, value: Any) -> None:
                    if key in self and not key.startswith("__"):
                        raise TypeError(f"{key!r} defined twice in the class body")
                    super().__setitem__(key, value)


            class NoDuplicatesMeta(type):
                @classmethod
                def __prepare__(
                    mcls, name: str, bases: tuple[type, ...], **kwargs: Any
                ) -> NoDuplicatesNamespace:
                    return NoDuplicatesNamespace()

                def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
                    return super().__new__(mcls, name, bases, dict(namespace))


            def define_duplicate_method() -> type:
                class PriceRules(metaclass=NoDuplicatesMeta):
                    def discount(self) -> int:
                        return 10

                    def discount(self) -> int:  # noqa: F811 (the mistake being caught)
                        return 20

                return PriceRules


            print(raised_message(define_duplicate_method))
            """
        ),
        md(
            """
            #### `ABCMeta`

            `abc.ABC` is a plain class whose metaclass is `ABCMeta`. Its `__new__` computes
            `__abstractmethods__`; its `__instancecheck__` / `__subclasscheck__` power
            `register` and `__subclasshook__` (Unit 2.3.2).
            """
        ),
        code(
            """
            class Shape(ABC):
                @abstractmethod
                def area(self) -> float: ...


            print(f"{type(ABC).__name__=}, {type(Shape).__name__=}")
            print(f"{Shape.__abstractmethods__=}")
            print(f"{[name for name in vars(ABCMeta) if name.startswith('__') and 'check' in name]=}")
            Shape.register(complex)
            print(f"{isinstance(1j, Shape)=}  (ABCMeta.__instancecheck__ honours register)")
            """
        ),
        md(
            """
            #### `EnumMeta`

            `enum.Enum`'s metaclass is `EnumType` (`EnumMeta` is the old name, still an
            alias). It uses **every** hook: `__prepare__` returns an `enum.EnumDict` (public
            since 3.13) that turns assignments into members, `__new__` builds the member
            objects, `__call__` makes `Colour(1)` a **lookup** instead of a construction, and
            `__iter__` / `__len__` / `__contains__` on the metaclass make the class itself
            iterable. That last point is Unit 2.4.9 again: `len(Colour)` looks on
            `type(Colour)`.
            """
        ),
        code(
            """
            class Colour(enum.Enum):
                RED = 1
                GREEN = 2


            print(f"{type(Colour).__name__=}, {enum.EnumMeta is enum.EnumType=}")
            print(f"{type(type(Colour).__prepare__('Size', (enum.Enum,))).__name__=}  (New in 3.13: public)")
            print(f"{Colour(1)=}  (EnumType.__call__ looks the member up)")
            print(f"{len(Colour)=}, {list(Colour)=}, {Colour.RED in Colour=}")
            print(f"{'__len__' in vars(enum.EnumType)=}, {'__len__' in vars(Colour)=}")
            """
        ),
        md(
            """
            > **Warning:** a class can have only one metaclass. Combining bases whose
            > metaclasses are unrelated fails, which is a big reason to prefer the lighter tools
            > in 2.5.8.
            """
        ),
        code(
            """
            print(raised_message(lambda: type("Mixed", (Customer, Notifier), {})))
            """
        ),
    ]


def _lighter_cells() -> list[NotebookNode]:
    """2.5.8 Lighter alternatives."""
    return [
        md(
            """
            ### 2.5.8 Lighter alternatives

            Most metaclass jobs (validate or register subclasses, add methods) are done more
            simply with two tools that do not conflict with other metaclasses:

            | Tool | Runs | Inherited? | Good for |
            | --- | --- | --- | --- |
            | `__init_subclass__` (PEP 487) | on the **parent**, each time a subclass is created | yes | validating/configuring subclasses, registries, class keywords |
            | Class decorator | once, on the class it decorates | no | adding or wrapping methods on one class |
            | Metaclass | at class creation and on every call | yes | changing the namespace before the body (`__prepare__`), class-level dunders, instance creation |

            **`__init_subclass__`** is an implicit class method on the base. Extra keywords in
            the class statement (`class Orders(ApiEndpoint, path="/orders")`) arrive as keyword
            arguments. This base validates and stores a URL path for each endpoint.
            """
        ),
        code(
            '''
            class ApiEndpoint:
                """Every subclass must declare a path that starts with '/'."""

                path: str

                def __init_subclass__(
                    cls, /, *, path: str, methods: tuple[str, ...] = ("GET",), **kwargs: Any
                ) -> None:
                    super().__init_subclass__(**kwargs)
                    if not path.startswith("/"):
                        raise ValueError(f"{cls.__name__}: path must start with '/', got {path!r}")
                    cls.path, cls.methods = path, methods


            class OrdersEndpoint(ApiEndpoint, path="/orders", methods=("GET", "POST")):
                pass


            print(f"{OrdersEndpoint.path=}, {OrdersEndpoint.methods=}")
            print(raised_message(lambda: type("BadEndpoint", (ApiEndpoint,), {}, path="orders")))
            print(raised_message(lambda: type("NoPath", (ApiEndpoint,), {})))
            '''
        ),
        md(
            """
            **Class decorators** receive the finished class and return it (or a replacement).
            `auto_repr` writes a `__repr__` from the `__init__` signature; `count_instances`
            wraps `__init__`. Unit 1.12.5 introduced the idea; `@dataclass` (Unit 2.6) is the
            best-known class decorator.
            """
        ),
        code(
            '''
            def auto_repr(cls: type) -> type:
                """Add a __repr__ listing the __init__ parameters."""
                parameter_names = list(inspect.signature(cls.__init__).parameters)[1:]

                def __repr__(self: Any) -> str:
                    pairs = ", ".join(f"{name}={getattr(self, name)!r}" for name in parameter_names)
                    return f"{type(self).__name__}({pairs})"

                cls.__repr__ = __repr__
                return cls


            def count_instances(cls: type) -> type:
                """Wrap __init__ so cls.instance_count tracks how many objects were made."""
                original_init = cls.__init__

                @functools.wraps(original_init)
                def counting_init(self: Any, *args: Any, **kwargs: Any) -> None:
                    original_init(self, *args, **kwargs)
                    cls.instance_count += 1

                cls.instance_count = 0
                cls.__init__ = counting_init
                return cls
            '''
        ),
        md("Stacked on one class, applied bottom-up:"),
        code(
            """
            @auto_repr
            @count_instances
            class Warehouse:
                def __init__(self, code: str, city: str) -> None:
                    self.code, self.city = code, city


            warehouses = [Warehouse("PNQ1", "Pune"), Warehouse("BLR2", "Bengaluru")]
            print(warehouses)
            print(f"{Warehouse.instance_count=}, {Warehouse.__init__.__name__=}")
            """
        ),
    ]


def _libraries_cells() -> list[NotebookNode]:
    """2.5.9 How libraries do it."""
    return [
        md(
            """
            ### 2.5.9 How libraries do it

            The famous "magic" libraries are built from the tools of this unit:

            | Library | Class-creation hook | Attribute machinery | What you write |
            | --- | --- | --- | --- |
            | Pydantic v2 | metaclass `ModelMetaclass` reads annotations into `model_fields` | validation in `__init__` (Rust core); fields are plain instance data | `class User(BaseModel): name: str` |
            | SQLAlchemy 2.0 | `DeclarativeBase.__init_subclass__` maps the class to a table | `InstrumentedAttribute` **descriptors**: class access builds SQL expressions, instance access returns values and tracks changes | `name: Mapped[str] = mapped_column()` |
            | Django models | metaclass `ModelBase` collects fields and the inner `class Meta` into `_meta` | field descriptors (deferred loading, related objects) | `name = models.CharField(max_length=50)` |
            | dataclasses | **class decorator**, no metaclass | generates `__init__`, `__repr__`, `__eq__` as source code and `exec`s it | `@dataclass class User: name: str` |
            | attrs | class decorator (`@define`, slots by default) | generated methods, optional validators | `@define class User: name: str` |

            Pydantic, SQLAlchemy and Django are Phase 6 dependencies and are not installed
            yet. The next cell checks; each library then gets a tiny stand-in that uses the
            same mechanism, so you can see it work.
            """
        ),
        code(
            """
            for library_name in ["pydantic", "sqlalchemy", "django", "attrs"]:
                installed = importlib.util.find_spec(library_name) is not None
                status = "installed" if installed else "not installed: skipping the real library"
                print(f"{library_name:<11} {status}")
            if importlib.util.find_spec("pydantic") is not None:
                import pydantic

                print(f"{type(pydantic.BaseModel).__name__=}")
            """
        ),
        md(
            """
            #### Pydantic-style: annotations + validation on `__init__`

            `__init_subclass__` reads each subclass's annotations once (with
            `annotationlib.get_annotations`, *New in 3.14*, which works with lazily evaluated
            annotations) and `__init__` checks and converts values against them. Pydantic does
            the same in Rust, with far more types and conversions.
            """
        ),
        code(
            '''
            class MiniModel:
                """Validates keyword arguments against the class annotations."""

                model_fields: dict[str, type] = {}

                def __init_subclass__(cls, **kwargs: Any) -> None:
                    super().__init_subclass__(**kwargs)
                    cls.model_fields = dict(annotationlib.get_annotations(cls))

                def __init__(self, **values: Any) -> None:
                    for field_name, field_type in self.model_fields.items():
                        if field_name not in values:
                            raise TypeError(f"missing field {field_name!r}")
                        raw_value = values[field_name]
                        try:
                            setattr(self, field_name, field_type(raw_value))  # lax conversion, like Pydantic
                        except TypeError, ValueError:
                            raise ValueError(
                                f"{field_name}: cannot convert {raw_value!r} to {field_type.__name__}"
                            ) from None


            class SignupForm(MiniModel):
                username: str
                age: int


            form = SignupForm(username="asha", age="29")
            print(f"{SignupForm.model_fields=}, {form.age=} ({type(form.age).__name__})")
            print(raised_message(lambda: SignupForm(username="ravi", age="twenty")))
            '''
        ),
        md(
            """
            #### SQLAlchemy-style: a descriptor that answers differently on the class

            The trick behind `select(User).where(User.age > 18)`: on the **class**, `__get__`
            returns an expression object whose comparison operators (Unit 2.4.4) build SQL
            text instead of returning `bool`; on an **instance**, it returns the value and
            records the change for the next flush.
            """
        ),
        code(
            """
            class ColumnExpression:
                def __init__(self, column_name: str) -> None:
                    self.column_name = column_name

                def __gt__(self, value: object) -> tuple[str, object]:
                    return (f"{self.column_name} > ?", value)

                def __eq__(self, value: object) -> tuple[str, object]:  # type: ignore[override]
                    return (f"{self.column_name} = ?", value)


            class MappedColumn:
                def __set_name__(self, owner: type, name: str) -> None:
                    self.name = name

                def __get__(self, instance: Any, owner: type | None = None) -> Any:
                    if instance is None:
                        return ColumnExpression(self.name)
                    return instance.__dict__.get(self.name)

                def __set__(self, instance: Any, value: object) -> None:
                    instance.__dict__[self.name] = value
                    instance.__dict__.setdefault("_dirty", set()).add(self.name)


            class UserRow:
                age = MappedColumn()
                city = MappedColumn()


            print(f"{(UserRow.age > 18)=}, {(UserRow.city == 'Pune')=}")
            row = UserRow()
            row.age = 30
            print(f"{row.age=}, {row._dirty=}  (changed columns waiting for a flush)")
            """
        ),
        md(
            """
            #### Django-style: a metaclass that collects fields and `class Meta`

            Django's `ModelBase.__new__` pulls field objects and the inner `Meta` class out of
            the namespace and builds one `_meta` options object per model. A miniature:
            """
        ),
        code(
            """
            class CharField:
                def __init__(self, max_length: int) -> None:
                    self.max_length = max_length


            class ModelOptions:
                def __init__(self, fields: dict[str, CharField], meta: type | None) -> None:
                    self.fields = fields
                    self.ordering = getattr(meta, "ordering", ())
                    self.verbose_name = getattr(meta, "verbose_name", None)


            class MiniModelBase(type):
                def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
                    fields = {key: value for key, value in namespace.items() if isinstance(value, CharField)}
                    meta = namespace.pop("Meta", None)
                    cls = super().__new__(mcls, name, bases, namespace)
                    cls._meta = ModelOptions(fields, meta)
                    return cls


            class Author(metaclass=MiniModelBase):
                name = CharField(max_length=80)
                city = CharField(max_length=40)

                class Meta:
                    ordering = ("name",)
                    verbose_name = "book author"


            print(f"{list(Author._meta.fields)=}, {Author._meta.ordering=}, {Author._meta.verbose_name=}")
            print(f"{hasattr(Author, 'Meta')=}  (consumed by the metaclass)")
            """
        ),
        md(
            """
            #### dataclasses: a class decorator that writes code

            `@dataclass` is just a function applied to the class. It reads the annotations,
            records them in `__dataclass_fields__`, **generates the source** of `__init__`,
            `__repr__` and `__eq__` and runs it with `exec`, which is why the generated
            `__init__` reports its file as `<string>` and `inspect.getsource` cannot find it.
            No metaclass is involved: the class's type is still `type`. attrs works the same way.
            """
        ),
        code(
            """
            @dataclasses.dataclass
            class Book:
                title: str
                price: Decimal


            print(f"{type(Book).__name__=}, {list(Book.__dataclass_fields__)=}")
            print(f"{Book.__init__.__code__.co_filename=}, {inspect.signature(Book)=}")
            print(raised_error_name(lambda: inspect.getsource(Book.__init__)))
            print(Book("Fluent Python", Decimal("3999")))
            if importlib.util.find_spec("attrs") is not None:
                import attrs

                @attrs.define
                class Magazine:
                    title: str

                print(f"{type(Magazine).__name__=}, {hasattr(Magazine('Wired'), '__dict__')=}")
                print("(attrs uses slots by default)")
            """
        ),
        *predict_cells(
            """
            class Order:
                def __init__(self, items):
                    self.items = items

                @property
                def total(self):
                    return sum(item.price for item in self.items)  # items are plain ints!

                def __getattr__(self, name):
                    return f"<missing {name}>"

            print(Order([10, 20]).total)
            """,
            """
            ```text
            <missing total>
            ```

            The property raises `AttributeError` (`int` has no `.price`). Python treats an
            `AttributeError` escaping from normal lookup, **including from inside a property
            getter**, as "attribute not found" and calls `__getattr__("total")`. The real bug is
            hidden. Keep `__getattr__` narrow (raise for names you do not handle), and be
            suspicious when a property seems to "disappear".
            """,
            """
            class Order:
                def __init__(self, items: list[int]) -> None:
                    self.items = items

                @property
                def total(self) -> int:
                    return sum(item.price for item in self.items)  # type: ignore[attr-defined]

                def __getattr__(self, name: str) -> str:
                    return f"<missing {name}>"


            print(Order([10, 20]).total)
            """,
        ),
    ]


def _lab_property_descriptor_cells() -> list[NotebookNode]:
    """Lab 2.5 exercises 1–3."""
    return [
        md(
            """
            ### Lab 2.5

            Five exercises. For each, complete the stub, then run the check cell. Until then the
            checks print FAIL; that is expected. In exercise 4 one check ("registry is a class
            attribute") already passes on the stub, because the stub declares the dict; keep it
            passing. The check cells define their test classes **inside functions**, so a stub
            that raises cannot stop Run All.

            #### Exercise 1 — rebuild `property`

            `MyProperty(fget=None, fset=None, fdel=None, doc=None)` must work like the
            built-in:

            - As a decorator; `.getter(f)`, `.setter(f)` and `.deleter(f)` return a **new**
              `MyProperty` with that function replaced (the original is unchanged).
            - `__set_name__` remembers the attribute name; class access returns the descriptor.
            - Missing functions raise `AttributeError(f"property {name!r} has no getter")`
              (or `setter` / `deleter`).
            - Keep the functions in the attributes `fget`, `fset` and `fdel`.
            - `__doc__` is `doc`, or else `fget.__doc__`. It must be a **data** descriptor even
              without a setter.
            """
        ),
        code(
            '''
            class MyProperty:
                """A pure-Python property."""

                def __init__(
                    self,
                    fget: Callable[[Any], Any] | None = None,
                    fset: Callable[[Any, Any], None] | None = None,
                    fdel: Callable[[Any], None] | None = None,
                    doc: str | None = None,
                ) -> None:
                    raise NotImplementedError("Lab 2.5: implement MyProperty")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def make_thermostat_class() -> type:
                """A class using MyProperty with a validating setter, a deleter and a read-only one."""

                class Thermostat:
                    def __init__(self) -> None:
                        self._target = 21

                    @MyProperty
                    def target(self) -> int:
                        """Target temperature in °C."""
                        return self._target

                    @target.setter
                    def target(self, value: int) -> None:
                        if not 5 <= value <= 30:
                            raise ValueError("target must be between 5 and 30")
                        self._target = value

                    @target.deleter
                    def target(self) -> None:
                        self._target = 21

                    @MyProperty
                    def serial(self) -> str:
                        return "TH-001"

                return Thermostat


            def thermostat_session() -> list[object]:
                """Read, set, reject, delete."""
                thermostat = make_thermostat_class()()
                answers: list[object] = [thermostat.target]
                thermostat.target = 25
                answers.append(thermostat.target)
                answers.append(raised_message(lambda: set_attribute(thermostat, "target", 99)))
                del thermostat.target
                answers.append(thermostat.target)
                return answers


            def setter_returns_copy() -> tuple[bool, bool]:
                """setter() builds a new object and leaves the original without a setter."""
                original = MyProperty(lambda self: 1)
                with_setter = original.setter(lambda self, value: None)
                return with_setter is not original, original.fset is None


            run_checks(
                [
                    (
                        "session",
                        thermostat_session,
                        [21, 25, "ValueError: target must be between 5 and 30", 21],
                    ),
                    (
                        "read-only",
                        lambda: raised_message(lambda: set_attribute(make_thermostat_class()(), "serial", "x")),
                        "AttributeError: property 'serial' has no setter",
                    ),
                    (
                        "no deleter",
                        lambda: raised_message(lambda: make_thermostat_class()().__delattr__("serial")),
                        "AttributeError: property 'serial' has no deleter",
                    ),
                    (
                        "class access",
                        lambda: type(vars(make_thermostat_class())["target"]).__name__,
                        "MyProperty",
                    ),
                    (
                        "doc from getter",
                        lambda: vars(make_thermostat_class())["target"].__doc__,
                        "Target temperature in °C.",
                    ),
                    ("explicit doc", lambda: MyProperty(doc="custom").__doc__, "custom"),
                    ("setter returns a copy", setter_returns_copy, (True, True)),
                    ("data descriptor", lambda: inspect.isdatadescriptor(MyProperty(lambda self: 1)), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `Typed` and `Bounded` descriptors

            Two reusable **data** descriptors that use `__set_name__` and store the value in the
            instance `__dict__` under the **same** name (the data descriptor still wins):

            - `Typed(expected_type)`: assigning a value that is not an instance raises
              `TypeError(f"{name} must be {expected_type.__name__}, got {type(value).__name__}")`.
            - `Bounded(minimum=None, maximum=None)`: values below or above raise
              `ValueError(f"{name} must be >= {minimum}")` / `ValueError(f"{name} must be <= {maximum}")`;
              `None` means no bound.
            - Both: reading before any assignment raises
              `AttributeError(f"{name} has not been set")`; class access returns the
              descriptor.
            """
        ),
        code(
            """
            class Typed:
                def __init__(self, expected_type: type) -> None:
                    raise NotImplementedError("Lab 2.5: implement Typed")


            class Bounded:
                def __init__(self, minimum: float | None = None, maximum: float | None = None) -> None:
                    raise NotImplementedError("Lab 2.5: implement Bounded")
            """
        ),
        md("Run the checks."),
        code(
            """
            def make_booking_class() -> type:
                class Booking:
                    guest_name = Typed(str)
                    guests = Bounded(minimum=1, maximum=10)
                    discount_percent = Bounded(maximum=50)

                    def __init__(self, guest_name: str, guests: int) -> None:
                        self.guest_name = guest_name
                        self.guests = guests

                return Booking


            run_checks(
                [
                    (
                        "valid",
                        lambda: vars(make_booking_class()("Asha", 4)),
                        {"guest_name": "Asha", "guests": 4},
                    ),
                    (
                        "type error",
                        lambda: raised_message(lambda: make_booking_class()(42, 2)),
                        "TypeError: guest_name must be str, got int",
                    ),
                    (
                        "below minimum",
                        lambda: raised_message(lambda: make_booking_class()("Ravi", 0)),
                        "ValueError: guests must be >= 1",
                    ),
                    (
                        "above maximum",
                        lambda: raised_message(lambda: make_booking_class()("Ravi", 11)),
                        "ValueError: guests must be <= 10",
                    ),
                    (
                        "open lower bound",
                        lambda: raised_message(
                            lambda: set_attribute(make_booking_class()("Ravi", 2), "discount_percent", -5)
                        ),
                        "no error",
                    ),
                    (
                        "upper bound only",
                        lambda: raised_message(
                            lambda: set_attribute(make_booking_class()("Ravi", 2), "discount_percent", 60)
                        ),
                        "ValueError: discount_percent must be <= 50",
                    ),
                    (
                        "not set yet",
                        lambda: raised_message(lambda: make_booking_class()("Ravi", 2).discount_percent),
                        "AttributeError: discount_percent has not been set",
                    ),
                    (
                        "class access",
                        lambda: [
                            type(vars(make_booking_class())[name]).__name__ for name in ("guest_name", "guests")
                        ],
                        ["Typed", "Bounded"],
                    ),
                    (
                        "data descriptors",
                        lambda: inspect.isdatadescriptor(Typed(int)) and inspect.isdatadescriptor(Bounded(0)),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — a caching `LazyAttribute`

            `LazyAttribute(func)` is a decorator for expensive computed attributes, like
            `functools.cached_property` (Unit 2.1.6):

            - On first access it calls `func(instance)`, stores the result in
              `instance.__dict__` under the attribute name, and returns it. Make it a
              **non-data** descriptor (only `__get__`), so later reads find the stored value
              and never call the descriptor again.
            - Class access returns the descriptor. `del instance.attribute` forgets the value,
              so the next read recomputes it. Assigning a value simply replaces it.
            """
        ),
        code(
            '''
            class LazyAttribute:
                """Compute once per instance, then behave like a normal attribute."""

                def __init__(self, func: Callable[[Any], Any]) -> None:
                    raise NotImplementedError("Lab 2.5: implement LazyAttribute")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def make_report_class() -> type:
                class SalesReport:
                    computations = 0

                    def __init__(self, amounts: list[int]) -> None:
                        self.amounts = amounts

                    @LazyAttribute
                    def total(self) -> int:
                        type(self).computations += 1
                        return sum(self.amounts)

                return SalesReport


            def lazy_session() -> list[object]:
                """Two reads, a second instance, delete and recompute, assign."""
                report_class = make_report_class()
                report = report_class([100, 250])
                answers: list[object] = [report.total, report.total, report_class.computations]
                answers.append("total" in vars(report))
                answers.append(report_class([1]).total)
                del report.total
                report.amounts.append(50)
                answers.extend([report.total, report_class.computations])
                report.total = 0
                answers.append(report.total)
                return answers


            run_checks(
                [
                    ("session", lazy_session, [350, 350, 1, True, 1, 400, 3, 0]),
                    (
                        "class access",
                        lambda: type(vars(make_report_class())["total"]).__name__,
                        "LazyAttribute",
                    ),
                    ("non-data descriptor", lambda: inspect.isdatadescriptor(LazyAttribute(len)), False),
                    ("has __get__", lambda: hasattr(LazyAttribute(len), "__get__"), True),
                ]
            )
            '''
        ),
    ]


def _lab_plugin_orm_cells() -> list[NotebookNode]:
    """Lab 2.5 exercises 4–5."""
    return [
        md(
            """
            #### Exercise 4 — a `PluginBase` registry with `__init_subclass__`

            Every subclass of `PluginBase` registers itself in the class attribute
            `PluginBase.registry` (name → class) **without a metaclass**:

            - The name comes from a class keyword, `class CsvExport(PluginBase,
              plugin_name="csv")`, defaulting to the lower-cased class name; store it on the
              subclass as `plugin_name`.
            - A second plugin with a taken name raises
              `ValueError(f"duplicate plugin name: {name!r}")`.
            - `PluginBase.create(name, *args, **kwargs)` instantiates a registered plugin
              (`KeyError` for unknown names); `PluginBase.available()` returns the sorted names.
            """
        ),
        code(
            '''
            class PluginBase:
                """Subclasses register themselves by name."""

                registry: dict[str, type[PluginBase]] = {}

                def __init_subclass__(cls, /, *, plugin_name: str | None = None, **kwargs: Any) -> None:
                    raise NotImplementedError("Lab 2.5: implement PluginBase.__init_subclass__")

                @classmethod
                def create(cls, name: str, *args: Any, **kwargs: Any) -> PluginBase:
                    raise NotImplementedError("Lab 2.5: implement PluginBase.create")

                @classmethod
                def available(cls) -> list[str]:
                    raise NotImplementedError("Lab 2.5: implement PluginBase.available")
            '''
        ),
        md("Run the checks. Each check starts from an empty registry."),
        code(
            '''
            def define_plugins() -> dict[str, type]:
                """Define three plugins on a fresh registry."""
                PluginBase.registry.clear()

                class CsvExport(PluginBase, plugin_name="csv"):
                    def __init__(self, delimiter: str = ",") -> None:
                        self.delimiter = delimiter

                class JsonExport(PluginBase):
                    pass

                class PdfExport(PluginBase, plugin_name="pdf"):
                    pass

                return {"CsvExport": CsvExport, "JsonExport": JsonExport, "PdfExport": PdfExport}


            def duplicate_name() -> None:
                """A second plugin called 'csv'."""
                define_plugins()
                type("OtherCsv", (PluginBase,), {}, plugin_name="csv")


            run_checks(
                [
                    (
                        "registered names",
                        lambda: sorted(define_plugins()["CsvExport"].registry),
                        ["csv", "jsonexport", "pdf"],
                    ),
                    (
                        "available()",
                        lambda: (define_plugins(), PluginBase.available())[1],
                        ["csv", "jsonexport", "pdf"],
                    ),
                    (
                        "plugin_name stored",
                        lambda: [plugin.plugin_name for plugin in define_plugins().values()],
                        ["csv", "jsonexport", "pdf"],
                    ),
                    (
                        "create with args",
                        lambda: (define_plugins(), PluginBase.create("csv", delimiter=";").delimiter)[1],
                        ";",
                    ),
                    (
                        "create type",
                        lambda: (define_plugins(), type(PluginBase.create("pdf")).__name__)[1],
                        "PdfExport",
                    ),
                    (
                        "unknown name",
                        lambda: (define_plugins(), raised_error_name(lambda: PluginBase.create("xml")))[1],
                        "KeyError",
                    ),
                    (
                        "duplicate",
                        lambda: raised_message(duplicate_name),
                        "ValueError: duplicate plugin name: 'csv'",
                    ),
                    ("no metaclass", lambda: type(define_plugins()["PdfExport"]).__name__, "type"),
                    ("registry is a class attribute", lambda: "registry" in vars(PluginBase), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — a mini ORM with `Field` descriptors

            Build the core of an ORM and run its SQL against an in-memory SQLite database.

            - `Field(sql_type, *, python_type, primary_key=False, nullable=True)` is a data
              descriptor. `__set_name__` records `name`; instance values live in the instance
              `__dict__`; reading an unset field returns `None`. Assigning `None` to a
              non-nullable field raises `ValueError(f"{name} cannot be NULL")`; a value of the
              wrong type raises `TypeError(f"{name} must be {python_type.__name__}")`.
            - `field.column_sql()` → `"id INTEGER PRIMARY KEY"`, `"name TEXT NOT NULL"`,
              `"email TEXT"` (`PRIMARY KEY` replaces `NOT NULL`).
            - `Model.__init_subclass__` collects the subclass's `Field`s **in definition order**
              into `cls.fields` (a dict) and sets `cls.table_name` to the class attribute if the
              class defines one, else the lower-cased class name plus `"s"`.
            - `Model(**values)` assigns every field (missing ones get `None`, so non-nullable
              fields must be given); an unknown keyword raises
              `TypeError(f"unknown field: {name}")`.
            - `Model.create_table_sql()` (class method) →
              `"CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)"`.
            - `instance.insert_sql()` → `("INSERT INTO users (id, name, email) VALUES (?, ?, ?)",
              (1, 'Asha', None))`; `repr` → `User(id=1, name='Asha', email=None)`.

            `IntegerField` and `TextField` are given.
            """
        ),
        code(
            '''
            class Field:
                """A typed column stored on model instances."""

                def __init__(
                    self,
                    sql_type: str,
                    *,
                    python_type: type,
                    primary_key: bool = False,
                    nullable: bool = True,
                ) -> None:
                    raise NotImplementedError("Lab 2.5: implement Field")


            class IntegerField(Field):
                def __init__(self, *, primary_key: bool = False, nullable: bool = True) -> None:
                    super().__init__("INTEGER", python_type=int, primary_key=primary_key, nullable=nullable)


            class TextField(Field):
                def __init__(self, *, primary_key: bool = False, nullable: bool = True) -> None:
                    super().__init__("TEXT", python_type=str, primary_key=primary_key, nullable=nullable)


            class Model:
                """Base class: collects fields and writes SQL."""

                fields: dict[str, Field] = {}
                table_name: str = ""

                def __init__(self, **values: Any) -> None:
                    raise NotImplementedError("Lab 2.5: implement Model")
            '''
        ),
        md("Run the checks. `define_models()` declares two models; the last check runs the SQL."),
        code(
            '''
            def define_models() -> tuple[type, type]:
                class User(Model):
                    id = IntegerField(primary_key=True)
                    name = TextField(nullable=False)
                    email = TextField()

                class Person(Model):
                    table_name = "people"
                    person_id = IntegerField(primary_key=True)

                return User, Person


            def round_trip() -> list[tuple[object, ...]]:
                """Create the table, insert two users, read them back."""
                user_class, _ = define_models()
                connection = sqlite3.connect(":memory:")
                connection.execute(user_class.create_table_sql())
                for user in (
                    user_class(id=1, name="Asha"),
                    user_class(id=2, name="Ravi", email="ravi@example.com"),
                ):
                    connection.execute(*user.insert_sql())
                rows = connection.execute("SELECT id, name, email FROM users ORDER BY id").fetchall()
                connection.close()
                return rows


            run_checks(
                [
                    ("fields in order", lambda: list(define_models()[0].fields), ["id", "name", "email"]),
                    (
                        "table names",
                        lambda: [model.table_name for model in define_models()],
                        ["users", "people"],
                    ),
                    (
                        "column sql",
                        lambda: [field.column_sql() for field in define_models()[0].fields.values()],
                        ["id INTEGER PRIMARY KEY", "name TEXT NOT NULL", "email TEXT"],
                    ),
                    (
                        "create table",
                        lambda: define_models()[0].create_table_sql(),
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)",
                    ),
                    (
                        "insert sql",
                        lambda: define_models()[0](id=1, name="Asha").insert_sql(),
                        ("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", (1, "Asha", None)),
                    ),
                    (
                        "repr",
                        lambda: repr(define_models()[0](id=1, name="Asha")),
                        "User(id=1, name='Asha', email=None)",
                    ),
                    (
                        "not null",
                        lambda: raised_message(lambda: define_models()[0](id=1)),
                        "ValueError: name cannot be NULL",
                    ),
                    (
                        "type check",
                        lambda: raised_message(lambda: define_models()[0](id="1", name="Asha")),
                        "TypeError: id must be int",
                    ),
                    (
                        "unknown field",
                        lambda: raised_message(lambda: define_models()[0](id=1, name="A", phone="9")),
                        "TypeError: unknown field: phone",
                    ),
                    (
                        "data descriptor",
                        lambda: inspect.isdatadescriptor(define_models()[0].__dict__["name"]),
                        True,
                    ),
                    ("sqlite round trip", round_trip, [(1, "Asha", None), (2, "Ravi", "ravi@example.com")]),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.5."""
    return [
        md(
            """
            ### Recap — Unit 2.5

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Lookup order | data descriptor → instance `__dict__` → non-data descriptor / class attribute → `__getattr__` | prototype chain |
            | `__getattr__` | Only for missing names: defaults, delegation, lazy loading | `Proxy` `get` trap (but that runs always) |
            | `__getattribute__` / `__setattr__` | Run on every access; use `super()` inside to avoid recursion | `Proxy` traps |
            | Descriptor | Class attribute with `__get__` / `__set__` / `__delete__`; `__set_name__` gives it its name | `Object.defineProperty` |
            | Data vs non-data | `__set__` or `__delete__` makes it beat the instance dict | — |
            | Methods | Functions are non-data descriptors; `__get__` returns the bound method | `.bind(this)`, done automatically |
            | `property` / `classmethod` / `staticmethod` | Small descriptors you can rebuild in a few lines | getters / `static` |
            | `__slots__` | No `__dict__`, fixed attributes, ~40 B less per instance on 3.15 | sealed objects |
            | `type(name, bases, ns)` | Classes are objects created by calling their metaclass | `class` expressions |
            | Metaclass | `__prepare__`, `__new__`, `__init__`, `__call__`; one per class | — |
            | `__init_subclass__` | Validate, configure or register subclasses without a metaclass | — |
            | Class decorator | Change one class after it is built | decorators (TC39) |
            | Libraries | Pydantic/Django: metaclasses; SQLAlchemy: descriptors; dataclasses/attrs: class decorators | — |

            **Further reading**

            - [Descriptor HowTo Guide](https://docs.python.org/3/howto/descriptor.html) (the
              pure-Python `property`, `classmethod` and lookup code),
              [Data model — customizing attribute access](https://docs.python.org/3/reference/datamodel.html#customizing-attribute-access)
            - [`__slots__`](https://docs.python.org/3/reference/datamodel.html#slots),
              [Metaclasses](https://docs.python.org/3/reference/datamodel.html#metaclasses),
              [`__init_subclass__`](https://docs.python.org/3/reference/datamodel.html#object.__init_subclass__),
              [`types.new_class`](https://docs.python.org/3/library/types.html#types.new_class)
            - [`annotationlib`](https://docs.python.org/3/library/annotationlib.html),
              [`enum.EnumType`](https://docs.python.org/3/library/enum.html#enum.EnumType),
              [`inspect.getattr_static`](https://docs.python.org/3/library/inspect.html#inspect.getattr_static)
            - [PEP 252 — Making types look more like classes](https://peps.python.org/pep-0252/),
              [PEP 3115 — Metaclasses in Python 3000](https://peps.python.org/pep-3115/),
              [PEP 487 — Simpler customisation of class creation](https://peps.python.org/pep-0487/),
              [PEP 749 — Implementing PEP 649 (lazy annotations)](https://peps.python.org/pep-0749/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.5 and Lab 2.5."""
    return [
        *_overview_cells(),
        *_lookup_cells(),
        *_hook_cells(),
        *_descriptor_cells(),
        *_builtin_descriptor_cells(),
        *_slots_cells(),
        *_classes_as_objects_cells(),
        *_metaclass_cells(),
        *_lighter_cells(),
        *_libraries_cells(),
        *_lab_property_descriptor_cells(),
        *_lab_plugin_orm_cells(),
        *_recap_cells(),
    ]
