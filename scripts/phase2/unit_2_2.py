"""Unit 2.2 — Inheritance, MRO and Composition (with Lab 2.2)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import importlib.util
import inspect
import itertools
import json
import socketserver
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol, override


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
            ## Unit 2.2 — Inheritance, MRO and Composition

            **Objectives**

            - Override and extend methods, and call the base class with `super().__init__`.
            - Explain zero-argument `super()` as "the next class in the MRO", not "the parent".
            - Compute a C3 linearization (MRO) by hand and recognize an inconsistent one.
            - Write mixins and order base classes correctly.
            - Prefer composition when inheritance would explode into many classes or break the
              Liskov substitution principle.
            - Recognize each SOLID principle in a short Python example.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `class B extends A` | `class B(A):` | Python allows **several** base classes |
            | `super(...)` must run before `this` is used | `super().__init__(...)` is optional and can run anywhere | Forget it and base attributes are silently missing |
            | `super.method()` (always the static parent, via `[[HomeObject]]`) | `super().method()` (the next class in `type(self).__mro__`) | Under multiple inheritance `super()` can call a **sibling** |
            | Prototype chain | `__mro__` (C3 linearization) | Computed once per class; base order matters |
            | Mixins via `Object.assign` or `Base => class extends Base {}` | Mixin classes listed before the base class | Order of bases decides which method wins |
            | `obj instanceof A` | `isinstance(obj, A)` / `issubclass(B, A)` | Accept tuples and `A | B` unions |
            | `Object.prototype` | `object` | Every class inherits from `object` |
            | TS `override` keyword | `@typing.override` (3.12+) | Checked by type checkers, not at run time |

            The next cell is this unit's setup. `mro_names(cls)` lists class names along
            `cls.__mro__`.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _single_inheritance_cells() -> list[NotebookNode]:
    """2.2.1 Single inheritance."""
    return [
        md(
            """
            ### 2.2.1 Single inheritance

            A subclass inherits every attribute of its base class and can **override** (replace)
            or **extend** (replace and call the original) any of them. The base class for this
            section is a parcel shipment.
            """
        ),
        code(
            '''
            class Shipment:
                """A parcel to deliver."""

                RATE_PER_KG = Decimal("40")

                def __init__(self, tracking_id: str, weight_kg: Decimal) -> None:
                    self.tracking_id = tracking_id
                    self.weight_kg = weight_kg

                def shipping_cost(self) -> Decimal:
                    """Price of delivery in rupees."""
                    return self.weight_kg * self.RATE_PER_KG

                def label(self) -> str:
                    """Text printed on the parcel."""
                    return f"{self.tracking_id}: {self.weight_kg} kg, INR {self.shipping_cost():.2f}"


            print(Shipment("TRK-1", Decimal("2.5")).label())
            '''
        ),
        md(
            """
            **Overriding.** `FragileShipment` replaces `shipping_cost` and reuses the original
            through `super()`. It does not touch `label`, yet the inherited `label` prints the
            new cost: `self.shipping_cost()` is looked up on the **instance's** class at call
            time (dynamic dispatch).

            `@override` (from `typing`, 3.12+) marks the intent. At run time it only sets
            `__override__ = True`; type checkers report an error if the base class has no
            method with that name, which catches typos like `shiping_cost`.
            """
        ),
        code(
            '''
            class FragileShipment(Shipment):
                """Costs more: a fixed handling fee on top of the weight-based price."""

                HANDLING_FEE = Decimal("75")

                @override
                def shipping_cost(self) -> Decimal:
                    return super().shipping_cost() + self.HANDLING_FEE


            vase = FragileShipment("TRK-2", Decimal("2.5"))
            print(vase.label())
            print(f"{FragileShipment.shipping_cost.__override__=}")
            print(f"{'label' in vars(FragileShipment)=}  (label is inherited, not copied)")
            '''
        ),
        md(
            """
            **Extending `__init__`.** A subclass that needs extra state defines its own
            `__init__`, calls `super().__init__(...)` for the base part, then sets its own
            attributes. It can extend other methods the same way.
            """
        ),
        code(
            '''
            class ExpressShipment(Shipment):
                """A shipment with a promised delivery date."""

                def __init__(self, tracking_id: str, weight_kg: Decimal, promised_by: date) -> None:
                    super().__init__(tracking_id, weight_kg)
                    self.promised_by = promised_by

                @override
                def label(self) -> str:
                    return f"{super().label()} | EXPRESS by {self.promised_by:%d %b}"


            express = ExpressShipment("TRK-3", Decimal("1"), date(2026, 11, 9))
            print(express.label())
            print(f"{vars(express)=}")
            '''
        ),
        md(
            """
            Forgetting `super().__init__` is not an error in Python (unlike JavaScript, where
            using `this` before `super()` throws). The object is created without the base
            attributes, and the failure shows up later, far from the cause.
            """
        ),
        code(
            '''
            class BrokenExpressShipment(Shipment):
                """BUG: never calls super().__init__."""

                def __init__(self, tracking_id: str, weight_kg: Decimal, promised_by: date) -> None:
                    self.promised_by = promised_by


            broken = BrokenExpressShipment("TRK-4", Decimal("1"), date(2026, 11, 9))
            print(f"{vars(broken)=}")
            print(raised_message(broken.label))
            '''
        ),
        md(
            """
            **`isinstance` and `issubclass`** follow the inheritance chain. Both accept a tuple
            of classes or a `X | Y` union (3.10+). Note that `bool` is a subclass of `int`, a
            classic surprise in validation code.
            """
        ),
        code(
            """
            print(f"{isinstance(vase, FragileShipment)=}, {isinstance(vase, Shipment)=}")
            print(f"{isinstance(vase, ExpressShipment)=}")
            print(f"{issubclass(ExpressShipment, Shipment)=}, {issubclass(Shipment, ExpressShipment)=}")
            print(f"{isinstance(vase, (ExpressShipment, FragileShipment))=}")
            print(f"{isinstance(42, int | str)=}, {issubclass(bool, int)=}, {isinstance(True, int)=}")
            """
        ),
        md(
            """
            **Everything inherits from `object`.** A class with no bases gets `object` as its
            only base, which is where default `__repr__`, `__eq__`, `__hash__`, `__init__` and
            friends come from. `__subclasses__()` lists direct subclasses (it holds weak
            references, so it reflects classes that still exist).
            """
        ),
        code(
            """
            print(f"{Shipment.__bases__=}")
            print(f"{mro_names(FragileShipment)=}")
            print(f"{sorted(klass.__name__ for klass in Shipment.__subclasses__())=}")
            print(f"{len(dir(object))=} attributes on object, e.g. {sorted(dir(object))[:5]}")
            print(f"{issubclass(type, object)=}, {isinstance(object, type)=}")
            """
        ),
    ]


def _super_cells() -> list[NotebookNode]:
    """2.2.2 super() in depth."""
    return [
        md(
            """
            ### 2.2.2 `super()` in depth

            **Zero-argument `super()`** is shorthand for `super(CurrentClass, self)`. The
            compiler sees `super` (or `__class__`) inside a method and gives the method a hidden
            closure cell named `__class__`, holding the class being defined (closures and cells:
            1.11). At call time `super()` reads that cell and the method's first argument.
            """
        ),
        code(
            """
            init_function = ExpressShipment.__init__
            print(f"{init_function.__code__.co_freevars=}")
            print(f"{init_function.__closure__[0].cell_contents=}")
            print(f"{super(ExpressShipment, express).label()=}  (the explicit two-argument form)")
            """
        ),
        md(
            """
            Because the cell is created by the class statement, `super()` in a function defined
            **outside** a class fails, even if you attach the function to a class later.
            """
        ),
        code(
            '''
            def orphan_label(self: Shipment) -> str:
                """Uses super() but was not defined inside a class body."""
                return super().label()


            Shipment.orphan_label = orphan_label
            print(raised_message(lambda: Shipment("TRK-5", Decimal("1")).orphan_label()))
            del Shipment.orphan_label
            '''
        ),
        md(
            """
            **"Next in MRO", not "parent".** `super()` means: in the MRO of `type(self)`, find
            the class *after* the one where this method is defined, and look the name up from
            there. With single inheritance that is the parent. With multiple inheritance it can
            be a **sibling**.

            Below, `Left.setup` calls `super().setup(...)`. On a plain `Left` instance that
            reaches `Base`. On a `Child` instance, whose MRO is `Child, Left, Right, Base`, the
            very same line reaches **`Right`**, a class `Left` knows nothing about.
            """
        ),
        code(
            """
            class Base:
                def setup(self, trace: list[str]) -> None:
                    trace.append("Base")


            class Left(Base):
                def setup(self, trace: list[str]) -> None:
                    trace.append("Left")
                    super().setup(trace)


            class Right(Base):
                def setup(self, trace: list[str]) -> None:
                    trace.append("Right")
                    super().setup(trace)


            class Child(Left, Right):
                def setup(self, trace: list[str]) -> None:
                    trace.append("Child")
                    super().setup(trace)


            for instance in [Left(), Child()]:
                setup_trace: list[str] = []
                instance.setup(setup_trace)
                print(f"{type(instance).__name__:<5} MRO {mro_names(type(instance))}  calls {setup_trace}")
            print(f"{super(Left, Child()).setup.__qualname__=}")
            """
        ),
        md(
            """
            **Cooperative `**kwargs`.** When several classes in one hierarchy each need
            constructor arguments, the pattern that works with any MRO is:

            1. Every `__init__` takes its own arguments as **keyword-only** and the rest as
               `**kwargs`.
            2. It removes what it needs and passes the rest on with `super().__init__(**kwargs)`.
            3. Every class calls `super()`, so the chain reaches `object.__init__`, which must
               receive **nothing**: a leftover keyword is a bug and raises `TypeError`.

            Notice that `CatalogItem` defines no `__init__` at all, yet both base classes run.
            """
        ),
        code(
            '''
            class Model:
                """Root of the cooperative chain."""

                def __init__(self, **kwargs: Any) -> None:
                    super().__init__(**kwargs)  # object.__init__ must receive nothing


            class Named(Model):
                def __init__(self, *, name: str, **kwargs: Any) -> None:
                    self.name = name
                    super().__init__(**kwargs)


            class Priced(Model):
                def __init__(self, *, price: Decimal, **kwargs: Any) -> None:
                    self.price = price
                    super().__init__(**kwargs)


            class CatalogItem(Named, Priced):
                """Gets both constructors through super(), in MRO order."""


            tea = CatalogItem(name="Tea", price=Decimal("120"))
            print(f"{vars(tea)=}, {mro_names(CatalogItem)=}")
            print(raised_message(lambda: CatalogItem(name="Tea", price=Decimal("1"), colour="red")))
            '''
        ),
    ]


def _mro_cells() -> list[NotebookNode]:
    """2.2.3 Multiple inheritance and the MRO."""
    return [
        md(
            """
            ### 2.2.3 Multiple inheritance and the MRO

            The **method resolution order** (MRO) is the list of classes Python searches for an
            attribute. Since Python 2.3 it is computed with the **C3 linearization**, which
            guarantees three things: a class comes before its bases, the order of bases in the
            `class` line is kept, and every class's MRO is consistent with its bases' MROs.

            **The rule.** For `class C(B1, B2, …, Bn)`:

            `L[C] = C + merge(L[B1], L[B2], …, L[Bn], [B1, B2, …, Bn])`

            `merge` repeatedly takes the **first head** (first element of a list) that does
            **not appear in the tail** (any later position) of any list, appends it to the
            result and removes it from the front of every list. If no head qualifies, the
            hierarchy is inconsistent and Python raises `TypeError`.

            **Worked example: a diamond.**

            ```text
            class Vehicle: ...
            class LandVehicle(Vehicle): ...
            class WaterVehicle(Vehicle): ...
            class Amphibious(LandVehicle, WaterVehicle): ...
            ```

            | Step | Lists still to merge | Candidate heads | Taken | Why |
            | --- | --- | --- | --- | --- |
            | 0 | `[LandVehicle, Vehicle, object]`, `[WaterVehicle, Vehicle, object]`, `[LandVehicle, WaterVehicle]` | — | `Amphibious` | the class itself goes first |
            | 1 | (same) | `LandVehicle` | `LandVehicle` | not in any tail |
            | 2 | `[Vehicle, object]`, `[WaterVehicle, Vehicle, object]`, `[WaterVehicle]` | `Vehicle` | — | `Vehicle` is in the tail of the second list: skip |
            | 3 | (same) | `WaterVehicle` | `WaterVehicle` | not in any tail |
            | 4 | `[Vehicle, object]`, `[Vehicle, object]` | `Vehicle` | `Vehicle` | now only ever a head |
            | 5 | `[object]`, `[object]` | `object` | `object` | done |

            Result: `Amphibious, LandVehicle, WaterVehicle, Vehicle, object`. The shared base
            `Vehicle` appears **once**, after both of its subclasses.
            """
        ),
        code(
            '''
            class Vehicle:
                def describe(self) -> str:
                    return "vehicle"


            class LandVehicle(Vehicle):
                def describe(self) -> str:
                    return "drives on land"


            class WaterVehicle(Vehicle):
                def describe(self) -> str:
                    return "floats on water"


            class Amphibious(LandVehicle, WaterVehicle):
                """Inherits describe() from the first class in its MRO that defines it."""


            print(f"{mro_names(Amphibious)=}")
            print(f"{Amphibious.mro() == list(Amphibious.__mro__) == list(inspect.getmro(Amphibious))=}")
            print(f"{Amphibious().describe()=}")
            '''
        ),
        md(
            """
            #### Under the hood: C3 step by step

            `c3_linearize` implements the rule above on class **names** and prints every step
            for the top-level class. The last line checks it against Python's own `__mro__`.
            """
        ),
        code(
            '''
            def c3_linearize(
                class_name: str, bases_of: dict[str, list[str]], verbose: bool = True
            ) -> list[str]:
                """C3 linearization of class_name, given each class's direct bases by name."""
                if not bases_of[class_name]:
                    return [class_name]
                lists = [c3_linearize(base, bases_of, False) for base in bases_of[class_name]]
                lists.append(list(bases_of[class_name]))
                result = [class_name]
                while any(lists):
                    for candidate_list in filter(None, lists):
                        head = candidate_list[0]
                        if not any(head in other[1:] for other in lists):
                            break
                    else:
                        raise TypeError(f"inconsistent hierarchy, stuck at {lists}")
                    if verbose:
                        print(f"merge {lists} -> take {head}")
                    result.append(head)
                    lists = [other[1:] if other and other[0] == head else other for other in lists]
                return result


            vehicle_bases = {"object": [], "Vehicle": ["object"], "LandVehicle": ["Vehicle"]}
            vehicle_bases |= {"WaterVehicle": ["Vehicle"], "Amphibious": ["LandVehicle", "WaterVehicle"]}
            print(f"{c3_linearize('Amphibious', vehicle_bases) == mro_names(Amphibious)=}")
            '''
        ),
        md(
            """
            **The diamond problem.** In C++ a diamond can give an object two copies of the
            shared base. In Python the MRO lists `Vehicle` once, so with cooperative `super()`
            its `__init__` runs **once**. Calling base classes by name instead
            (`Vehicle.__init__(self)` from both branches) runs it **twice**, which is how
            diamonds go wrong in practice.
            """
        ),
        code(
            """
            class Engine:
                def __init__(self, init_log: list[str]) -> None:
                    init_log.append("Engine")


            class ByNamePetrol(Engine):
                def __init__(self, init_log: list[str]) -> None:
                    Engine.__init__(self, init_log)  # explicit call by name


            class ByNameElectric(Engine):
                def __init__(self, init_log: list[str]) -> None:
                    Engine.__init__(self, init_log)


            class ByNameHybrid(ByNamePetrol, ByNameElectric):
                def __init__(self, init_log: list[str]) -> None:
                    ByNamePetrol.__init__(self, init_log)
                    ByNameElectric.__init__(self, init_log)


            by_name_log: list[str] = []
            ByNameHybrid(by_name_log)
            print(f"{by_name_log=}  (Engine initialized twice)")
            """
        ),
        md("The same diamond with `super()` everywhere: `Engine` runs exactly once."),
        code(
            """
            class Petrol(Engine):
                def __init__(self, init_log: list[str]) -> None:
                    init_log.append("Petrol")
                    super().__init__(init_log)


            class Electric(Engine):
                def __init__(self, init_log: list[str]) -> None:
                    init_log.append("Electric")
                    super().__init__(init_log)


            class Hybrid(Petrol, Electric):
                def __init__(self, init_log: list[str]) -> None:
                    init_log.append("Hybrid")
                    super().__init__(init_log)


            super_log: list[str] = []
            Hybrid(super_log)
            print(f"{super_log=}")
            """
        ),
        md(
            """
            **Inconsistent MROs.** Some base lists cannot be linearized, and Python refuses to
            create the class. Two common causes:

            1. Listing a base **before its own subclass** (`class Bad(Vehicle, LandVehicle)`):
               `Vehicle` must come first (base order) and after `LandVehicle` (subclass first).
            2. Two parents that order the same bases **differently**.
            """
        ),
        code(
            '''
            def define_class(name: str, bases: tuple[type, ...]) -> str:
                """Try to create a class; report its MRO or the error."""
                try:
                    return f"{mro_names(type(name, bases, {}))}"
                except TypeError as error:
                    return f"{type(error).__name__}: {error}"


            class FirstOrder(LandVehicle, WaterVehicle): ...


            class SecondOrder(WaterVehicle, LandVehicle): ...


            print(define_class("Bad", (Vehicle, LandVehicle)))
            print(define_class("Conflicted", (FirstOrder, SecondOrder)))
            print(define_class("Fine", (LandVehicle, Vehicle)))
            '''
        ),
        *predict_cells(
            """
            class A:
                def who(self): return "A"
            class B(A):
                def who(self): return "B+" + super().who()
            class C(A):
                def who(self): return "C+" + super().who()
            class D(C, B):
                pass

            print(D().who())
            print(B().who())
            """,
            """
            ```text
            C+B+A
            B+A
            ```

            `D`'s MRO is `D, C, B, A, object` (bases in the order written: `C` before `B`).
            `D` has no `who`, so `C.who` runs; its `super()` is the next class after `C` in
            **`D`'s** MRO, which is `B`, not `A`. On a plain `B` instance the MRO is
            `B, A, object`, so `B`'s `super()` reaches `A`.
            """,
            """
            class A:
                def who(self) -> str:
                    return "A"


            class B(A):
                def who(self) -> str:
                    return "B+" + super().who()


            class C(A):
                def who(self) -> str:
                    return "C+" + super().who()


            class D(C, B):
                pass


            print(D().who())
            print(B().who())
            """,
        ),
    ]


def _mixin_cells() -> list[NotebookNode]:
    """2.2.4 Mixins."""
    return [
        md(
            """
            ### 2.2.4 Mixins

            A **mixin** is a small class that adds one capability and is meant to be combined
            with other classes, never used alone. Good mixins:

            - do one thing (a `__repr__`, JSON export, timestamps);
            - keep little or no state of their own, and if they need `__init__`, take
              `**kwargs` and call `super().__init__(**kwargs)` (2.2.2);
            - are named `…Mixin` so readers know they are not standalone.

            Three mixins first. `ReprMixin` builds a `__repr__` from `vars(self)`.
            """
        ),
        code(
            '''
            class ReprMixin:
                """Adds a __repr__ built from the instance attributes."""

                def __repr__(self) -> str:
                    fields = ", ".join(f"{name}={value!r}" for name, value in vars(self).items())
                    return f"{type(self).__name__}({fields})"
            '''
        ),
        md(
            """
            `JsonSerializableMixin` dumps the instance attributes. This simple version only
            handles values `json` already understands; Lab 2.2 exercise 2 extends it to nested
            objects and datetimes.
            """
        ),
        code(
            '''
            class JsonSerializableMixin:
                """Adds to_json() for objects whose attributes are plain JSON values."""

                def to_json(self) -> str:
                    """Serialize vars(self) with json.dumps."""
                    return json.dumps(vars(self), sort_keys=True)
            '''
        ),
        md(
            """
            `TimestampMixin` needs state, so it has a **cooperative** `__init__`. Its clock is a
            class attribute, so tests (and this notebook) can swap in a fake clock and get
            deterministic output.
            """
        ),
        code(
            '''
            class TimestampMixin:
                """Adds created_at / updated_at, set from a replaceable clock."""

                clock: ClassVar[Callable[[], datetime]] = datetime.now

                def __init__(self, **kwargs: Any) -> None:
                    super().__init__(**kwargs)
                    self.created_at = self.clock()
                    self.updated_at = self.created_at

                def touch(self) -> None:
                    """Record a modification."""
                    self.updated_at = self.clock()


            fake_ticks = iter([datetime(2026, 11, 7, 9, 0), datetime(2026, 11, 7, 9, 45)])


            def fake_now() -> datetime:
                """Return the next scripted time."""
                return next(fake_ticks)
            '''
        ),
        md(
            """
            **Combining them.** The rule for base order: **mixins on the left, the main base
            class on the right**. The MRO then tries each mixin before the base, so a mixin can
            add or override behaviour, and the base sits at the end of the cooperative
            `__init__` chain.
            """
        ),
        code(
            '''
            class Entity:
                """The main base class: every stored object has an id."""

                def __init__(self, *, entity_id: int, **kwargs: Any) -> None:
                    super().__init__(**kwargs)
                    self.entity_id = entity_id


            class Product(ReprMixin, JsonSerializableMixin, TimestampMixin, Entity):
                """A product assembled from three mixins and one base class."""

                clock = staticmethod(fake_now)

                def __init__(self, *, sku: str, price_paise: int, **kwargs: Any) -> None:
                    super().__init__(**kwargs)
                    self.sku = sku
                    self.price_paise = price_paise


            soap = Product(entity_id=7, sku="SOAP", price_paise=4_950)
            soap.touch()
            print(f"{mro_names(Product)=}")
            print(soap)
            '''
        ),
        md(
            """
            The flat JSON mixin fails on the `datetime` attributes the timestamp mixin added:
            `json` does not know how to encode them. A plain class with only JSON-friendly
            values works fine. (Lab 2.2 exercise 2 fixes this.)
            """
        ),
        code(
            '''
            class Tag(JsonSerializableMixin):
                """Only JSON-friendly attributes."""

                def __init__(self, label: str, colour: str) -> None:
                    self.label = label
                    self.colour = colour


            print(Tag("organic", "green").to_json())
            print(raised_message(soap.to_json))
            '''
        ),
        md(
            """
            **Wrong order.** If the base class comes first and defines the same method, the
            mixin never gets a chance: `AuditedEntity.__repr__` is found before
            `ReprMixin.__repr__`.
            """
        ),
        code(
            '''
            class AuditedEntity(Entity):
                """A base class with its own __repr__."""

                def __repr__(self) -> str:
                    return f"<AuditedEntity {self.entity_id}>"


            class WrongOrder(AuditedEntity, ReprMixin):
                """Base first, mixin last: the mixin's __repr__ is shadowed."""


            class RightOrder(ReprMixin, AuditedEntity):
                """Mixin first: the mixin's __repr__ wins."""


            print(f"{mro_names(WrongOrder)=}")
            print(f"{WrongOrder(entity_id=1)!r}  vs  {RightOrder(entity_id=1)!r}")
            '''
        ),
        md(
            """
            **Mixins in Django and DRF.** Web frameworks lean heavily on mixins. Django's
            class-based views combine permission and behaviour mixins with a generic view, and
            Django REST Framework builds its generic API views from one mixin per action:

            ```python
            # Django: permission mixin first, generic view last
            class ArticleListView(LoginRequiredMixin, ListView):
                model = Article

            # Django REST Framework: one mixin per HTTP action, base view last
            class ArticleList(mixins.ListModelMixin, mixins.CreateModelMixin, generics.GenericAPIView):
                queryset = Article.objects.all()
                serializer_class = ArticleSerializer

                def get(self, request, *args, **kwargs):
                    return self.list(request, *args, **kwargs)   # from ListModelMixin

                def post(self, request, *args, **kwargs):
                    return self.create(request, *args, **kwargs)  # from CreateModelMixin
            ```

            Neither framework is a course dependency, so the cell below only checks whether
            they are installed. The standard library uses the same pattern:
            `socketserver.ThreadingTCPServer` is literally `ThreadingMixIn` + `TCPServer`.
            """
        ),
        code(
            """
            for package_name in ["django", "rest_framework"]:
                if importlib.util.find_spec(package_name) is None:
                    print(f"{package_name} is not installed: skipping (not needed for this course)")
                else:
                    print(f"{package_name} is installed")
            print(f"{mro_names(socketserver.ThreadingTCPServer)=}")
            """
        ),
    ]


def _composition_cells() -> list[NotebookNode]:
    """2.2.5 Composition over inheritance."""
    return [
        md(
            """
            ### 2.2.5 Composition over inheritance

            **Inheritance** models *is-a*: an `ExpressShipment` is a `Shipment` and can be used
            anywhere a `Shipment` is expected. **Composition** models *has-a*: an object keeps
            other objects as attributes and **delegates** work to them.

            | Question | If yes |
            | --- | --- |
            | Is every subclass instance usable wherever the base is expected, with no surprises? | Inheritance may fit |
            | Do you only want to *reuse some code*? | Composition |
            | Would you need one subclass per *combination* of features? | Composition |
            | Should the behaviour be swappable at run time or in tests? | Composition |

            **Inheriting from a built-in exposes too much.** A "top 3" list that subclasses
            `list` guards `append`, but every other mutating method (`extend`, `insert`, `+=`)
            walks straight past the rule.
            """
        ),
        code(
            '''
            class TopThreeList(list[str]):
                """BUG: is-a list, so every list method can break the size rule."""

                def append(self, item: str) -> None:
                    if len(self) >= 3:
                        raise ValueError("top three is full")
                    super().append(item)


            podium = TopThreeList()
            for runner in ["Asha", "Ravi", "Meena"]:
                podium.append(runner)
            print(raised_message(lambda: podium.append("John")))
            podium.extend(["John", "Fatima"])  # not guarded
            podium.insert(0, "Arjun")  # not guarded
            print(f"{podium=}, {len(podium)=}")
            '''
        ),
        md(
            """
            **Composition with explicit delegation.** `TopThree` *has* a list and exposes only
            what it wants. The rule cannot be bypassed because there is no `extend` or
            `insert` to call.
            """
        ),
        code(
            '''
            class TopThree:
                """Has a list; delegates only the safe operations to it."""

                def __init__(self) -> None:
                    self._runners: list[str] = []

                def add(self, runner: str) -> None:
                    """Add a finisher, refusing a fourth one."""
                    if len(self._runners) >= 3:
                        raise ValueError("top three is full")
                    self._runners.append(runner)

                def __len__(self) -> int:
                    return len(self._runners)

                def __iter__(self) -> Iterator[str]:
                    return iter(self._runners)


            podium = TopThree()
            for runner in ["Asha", "Ravi", "Meena"]:
                podium.add(runner)
            print(raised_message(lambda: podium.add("John")))
            print(f"{list(podium)=}, {len(podium)=}, {hasattr(podium, 'extend')=}")
            '''
        ),
        md(
            """
            **Automatic delegation with `__getattr__`.** Python calls `__getattr__` only when
            normal lookup fails, so a wrapper can forward every unknown attribute to the object
            it wraps (a proxy). Unit 2.5 covers attribute hooks in detail.
            """
        ),
        code(
            '''
            class RecordingProxy:
                """Forwards every unknown attribute to the wrapped object and records the name."""

                def __init__(self, target: object) -> None:
                    self._target = target
                    self.accessed: list[str] = []

                def __getattr__(self, name: str) -> Any:
                    self.accessed.append(name)
                    return getattr(self._target, name)


            proxied_text = RecordingProxy("  Hello, Pune  ")
            print(f"{proxied_text.strip().upper()=}")
            print(f"{proxied_text.count('l')=}")
            print(f"{proxied_text.accessed=}")
            '''
        ),
        md(
            """
            **Refactoring a `Notifier` hierarchy.** A notifier sends messages over a channel
            (e-mail, SMS) and may add features (logging, retries). With inheritance every
            combination needs its own class, and the feature code is copied into each one.
            """
        ),
        code(
            """
            class Notifier:
                def send(self, recipient: str, message: str) -> str:
                    raise NotImplementedError


            class EmailNotifier(Notifier):
                def send(self, recipient: str, message: str) -> str:
                    return f"email to {recipient}: {message}"


            class SmsNotifier(Notifier):
                def send(self, recipient: str, message: str) -> str:
                    return f"sms to {recipient}: {message}"


            class LoggingEmailNotifier(EmailNotifier):
                def __init__(self, log: list[str]) -> None:
                    self.log = log

                def send(self, recipient: str, message: str) -> str:
                    self.log.append(f"sending to {recipient}")  # duplicated in every Logging* class
                    return super().send(recipient, message)


            notifier_log: list[str] = []
            print(LoggingEmailNotifier(notifier_log).send("asha@example.com", "Order shipped"))
            print(f"{notifier_log=}")
            """
        ),
        md(
            """
            The class count grows **multiplicatively**: every channel times every subset of
            features. Adding one channel or one feature means writing many new classes.
            """
        ),
        code(
            '''
            def inheritance_class_count(channel_count: int, feature_count: int) -> int:
                """Classes needed for every channel with every subset of features."""
                return channel_count * 2**feature_count


            channels = ["Email", "Sms"]
            features = ["Logging", "Retrying"]
            combinations = [
                "".join(chosen) + channel + "Notifier"
                for channel in channels
                for size in range(len(features) + 1)
                for chosen in itertools.combinations(features, size)
            ]
            print(combinations)
            for channel_count, feature_count in [(2, 2), (3, 2), (3, 3), (4, 4)]:
                print(
                    f"{channel_count} channels, {feature_count} features -> "
                    f"{inheritance_class_count(channel_count, feature_count)} classes"
                )
            '''
        ),
        md(
            """
            **The composition version.** Each channel is a small class with `send()`. Each
            feature is a **wrapper** that has an inner channel and adds one behaviour (the
            decorator pattern, as objects). The `Notifier` has a channel. Classes now grow
            **additively** (channels + features), and combinations are built at run time.

            A `FlakyChannel` fails a fixed number of times so the retry feature can be
            demonstrated deterministically.
            """
        ),
        code(
            '''
            class EmailChannel:
                def send(self, recipient: str, message: str) -> str:
                    return f"email to {recipient}: {message}"


            class SmsChannel:
                def send(self, recipient: str, message: str) -> str:
                    return f"sms to {recipient}: {message}"


            class FlakyChannel:
                """Wraps a channel and raises ConnectionError for the first `failures` calls."""

                def __init__(self, inner: Any, failures: int) -> None:
                    self.inner = inner
                    self.failures_left = failures

                def send(self, recipient: str, message: str) -> str:
                    if self.failures_left > 0:
                        self.failures_left -= 1
                        raise ConnectionError("gateway timeout")
                    return self.inner.send(recipient, message)
            '''
        ),
        md("The two feature wrappers. Each has an `inner` channel and adds one behaviour:"),
        code(
            '''
            class LoggingChannel:
                """Feature: log each send attempt, then delegate."""

                def __init__(self, inner: Any, log: list[str]) -> None:
                    self.inner = inner
                    self.log = log

                def send(self, recipient: str, message: str) -> str:
                    self.log.append(f"sending to {recipient}")
                    return self.inner.send(recipient, message)


            class RetryingChannel:
                """Feature: retry on ConnectionError, up to `attempts` tries in total."""

                def __init__(self, inner: Any, attempts: int) -> None:
                    self.inner = inner
                    self.attempts = attempts

                def send(self, recipient: str, message: str) -> str:
                    for attempt in range(1, self.attempts + 1):
                        try:
                            return self.inner.send(recipient, message)
                        except ConnectionError:
                            if attempt == self.attempts:
                                raise
                    raise AssertionError("unreachable")
            '''
        ),
        md(
            """
            The `Notifier` only has a channel. It knows nothing about logging or retries, so it
            never changes when a feature is added.
            """
        ),
        code(
            '''
            class Notifier:
                """Has a channel; knows nothing about logging or retries."""

                def __init__(self, channel: Any) -> None:
                    self.channel = channel

                def notify(self, recipient: str, message: str) -> str:
                    return self.channel.send(recipient, message)
            '''
        ),
        md(
            """
            Any combination is now one expression. The SMS gateway fails twice; the retrying
            wrapper tries three times; the logging wrapper (inside the retry) records every
            attempt.
            """
        ),
        code(
            """
            delivery_log: list[str] = []
            reliable_sms = Notifier(
                RetryingChannel(
                    LoggingChannel(FlakyChannel(SmsChannel(), failures=2), delivery_log), attempts=3
                )
            )
            print(reliable_sms.notify("+91-98xxxxxx01", "OTP 4821"))
            print(f"{delivery_log=}")
            print(Notifier(EmailChannel()).notify("asha@example.com", "Order shipped"))
            print(
                raised_message(
                    lambda: Notifier(RetryingChannel(FlakyChannel(EmailChannel(), 5), 2)).notify("x", "y")
                )
            )
            """
        ),
        md(
            """
            **The Square/Rectangle Liskov violation.** The **Liskov substitution principle**
            (LSP) says code written for a base class must keep working, with no surprises, when
            given a subclass. Mathematically a square *is a* rectangle, so `Square(Rectangle)`
            looks natural. But a mutable `Rectangle` promises that setting `width` leaves
            `height` alone, and a square cannot keep that promise.
            """
        ),
        code(
            '''
            class Rectangle:
                """A mutable rectangle: width and height change independently."""

                def __init__(self, width: float, height: float) -> None:
                    self._width = width
                    self._height = height

                @property
                def width(self) -> float:
                    return self._width

                @width.setter
                def width(self, value: float) -> None:
                    self._width = value

                @property
                def height(self) -> float:
                    return self._height

                @height.setter
                def height(self, value: float) -> None:
                    self._height = value

                @property
                def area(self) -> float:
                    return self._width * self._height
            '''
        ),
        md(
            """
            `Square` keeps its sides equal by overriding both setters. `stretch_width` is
            written against `Rectangle` and relies on its promise; it works for a rectangle and
            silently breaks for a square, even though `isinstance(square, Rectangle)` is `True`.
            """
        ),
        code(
            '''
            class Square(Rectangle):
                """Keeps width == height, which breaks Rectangle's promise."""

                def __init__(self, side: float) -> None:
                    super().__init__(side, side)

                @Rectangle.width.setter
                def width(self, value: float) -> None:
                    self._width = self._height = value

                @Rectangle.height.setter
                def height(self, value: float) -> None:
                    self._width = self._height = value


            def stretch_width(shape: Rectangle, factor: float) -> str:
                """Client code: doubling the width should double the area."""
                expected_area = shape.area * factor
                shape.width *= factor
                return f"{type(shape).__name__}: expected {expected_area}, got {shape.area}"


            print(stretch_width(Rectangle(2, 3), 2))
            print(stretch_width(Square(3), 2))
            print(f"{isinstance(Square(3), Rectangle)=}")
            '''
        ),
        md(
            """
            **One fix:** make the shapes immutable values. "Changing" the width returns a **new**
            shape, so a square stretched in one direction honestly becomes a rectangle, and
            `Square` no longer needs to inherit from `Rectangle` at all. Lab 2.3 builds shapes
            this way behind a shared abstract base class.
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class FixedRectangle:
                width: float
                height: float

                def with_width(self, width: float) -> FixedRectangle:
                    return FixedRectangle(width, self.height)


            @dataclass(frozen=True)
            class FixedSquare:
                side: float

                def with_width(self, width: float) -> FixedRectangle:
                    return FixedRectangle(width, self.side)  # a stretched square is a rectangle


            print(f"{FixedSquare(3).with_width(6)=}")
            print(raised_error_name(lambda: setattr(FixedSquare(3), "side", 6)))
            """
        ),
    ]


def _solid_cells() -> list[NotebookNode]:
    """2.2.6 SOLID in Python."""
    return [
        md(
            """
            ### 2.2.6 SOLID in Python

            SOLID is five design principles from the object-oriented world. In Python they
            often take a lighter form (a function, a Protocol), but the ideas carry over.

            | Letter | Principle | One-line meaning |
            | --- | --- | --- |
            | S | Single responsibility | A class should have one reason to change |
            | O | Open/closed | Add behaviour by adding code, not by editing working code |
            | L | Liskov substitution | Subclasses must honour the base class's promises |
            | I | Interface segregation | Depend on small interfaces, not fat ones |
            | D | Dependency inversion | Depend on abstractions; inject concrete implementations |

            **S — Single responsibility.** An `Invoice` that computes totals, renders text and
            saves itself changes for three unrelated reasons (tax rules, layout, storage).
            Split it so each class has one.
            """
        ),
        code(
            '''
            class InvoiceCalculator:
                """Changes when tax rules change."""

                def total(self, line_amounts: list[Decimal], tax_rate_percent: Decimal) -> Decimal:
                    return sum(line_amounts, Decimal("0")) * (1 + tax_rate_percent / 100)


            class InvoiceRenderer:
                """Changes when the layout changes."""

                def render(self, invoice_number: str, total: Decimal) -> str:
                    return f"Invoice {invoice_number}: INR {total:.2f}"


            class InvoiceArchive:
                """Changes when storage changes."""

                def __init__(self) -> None:
                    self.saved: dict[str, str] = {}

                def save(self, invoice_number: str, text: str) -> None:
                    self.saved[invoice_number] = text


            invoice_total = InvoiceCalculator().total([Decimal("100"), Decimal("250")], Decimal("18"))
            invoice_archive = InvoiceArchive()
            invoice_archive.save("INV-9", InvoiceRenderer().render("INV-9", invoice_total))
            print(invoice_archive.saved)
            '''
        ),
        md(
            """
            **O — Open/closed.** `checkout_total` applies whatever discount rules it is given.
            A new rule is a new class; `checkout_total` never changes. (An `if rule == "…"`
            chain would have to be edited for every new rule.)
            """
        ),
        code(
            '''
            class PercentOff:
                def __init__(self, percent: Decimal) -> None:
                    self.percent = percent

                def apply(self, amount: Decimal) -> Decimal:
                    return amount * (1 - self.percent / 100)


            class FlatOff:
                def __init__(self, rupees: Decimal) -> None:
                    self.rupees = rupees

                def apply(self, amount: Decimal) -> Decimal:
                    return max(amount - self.rupees, Decimal("0"))


            def checkout_total(amount: Decimal, rules: Iterable[Any]) -> Decimal:
                """Closed for modification: new rules plug in without editing this function."""
                for rule in rules:
                    amount = rule.apply(amount)
                return amount


            weekend_rules = [PercentOff(Decimal("10")), FlatOff(Decimal("50"))]
            print(f"{checkout_total(Decimal('1000'), weekend_rules)=}")
            '''
        ),
        md(
            """
            **L — Liskov substitution.** Besides Square/Rectangle (2.2.5), a classic violation
            is a subclass that refuses an operation the base class promises. `warm_up` works for
            any `Cache`, and crashes for the `ReadOnlyCache` "subtype". The fix is to not make
            it a subclass (or to split the interface, as the next principle shows).
            """
        ),
        code(
            '''
            class Cache:
                def __init__(self) -> None:
                    self._entries: dict[str, str] = {}

                def get(self, key: str) -> str | None:
                    return self._entries.get(key)

                def set(self, key: str, value: str) -> None:
                    self._entries[key] = value


            class ReadOnlyCache(Cache):
                """BUG: strengthens the precondition of set() to 'never'."""

                def set(self, key: str, value: str) -> None:
                    raise PermissionError("read-only cache")


            def warm_up(cache: Cache) -> str | None:
                """Written against Cache: set, then get."""
                cache.set("home", "<html>…</html>")
                return cache.get("home")


            print(f"{warm_up(Cache())=}")
            print(raised_message(lambda: warm_up(ReadOnlyCache())))
            '''
        ),
        md(
            """
            **I — Interface segregation.** A report viewer only reads, so it should depend on a
            small "readable" interface, not on a fat storage interface with writes and deletes.
            `typing.Protocol` (2.3.3) describes such interfaces; `PublicMirror` only implements
            reading and still fits the viewer.
            """
        ),
        code(
            '''
            class Readable(Protocol):
                def read(self, key: str) -> str: ...


            class Writable(Protocol):
                def write(self, key: str, value: str) -> None: ...


            class ArchiveStore:
                """Implements both small interfaces."""

                def __init__(self) -> None:
                    self.data = {"q3": "revenue up 12%"}

                def read(self, key: str) -> str:
                    return self.data[key]

                def write(self, key: str, value: str) -> None:
                    self.data[key] = value


            class PublicMirror:
                """Read-only copy: implements only Readable."""

                def read(self, key: str) -> str:
                    return "revenue up 12% (mirror)"


            def show_report(store: Readable, key: str) -> str:
                """Needs reading only, so it asks for Readable."""
                return f"[{key}] {store.read(key)}"


            print(show_report(ArchiveStore(), "q3"))
            print(show_report(PublicMirror(), "q3"))
            '''
        ),
        md(
            """
            **D — Dependency inversion.** `OrderService` does not create its own database
            connection; it receives any object with `save` and `find`. Production passes a real
            repository, tests pass an in-memory one. FastAPI's `Depends` (Phase 6) is built on
            this idea.
            """
        ),
        code(
            '''
            class InMemoryOrderRepository:
                """A test double: stores orders in a dict."""

                def __init__(self) -> None:
                    self.orders: dict[str, Decimal] = {}

                def save(self, order_id: str, amount: Decimal) -> None:
                    self.orders[order_id] = amount

                def find(self, order_id: str) -> Decimal | None:
                    return self.orders.get(order_id)


            class OrderService:
                """High-level policy; the repository is injected, not constructed here."""

                def __init__(self, repository: Any) -> None:
                    self.repository = repository

                def place(self, order_id: str, amount: Decimal) -> str:
                    if self.repository.find(order_id) is not None:
                        return f"{order_id} already placed"
                    self.repository.save(order_id, amount)
                    return f"{order_id} placed"


            service = OrderService(InMemoryOrderRepository())
            print(service.place("ORD-1", Decimal("499")), "|", service.place("ORD-1", Decimal("499")))
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 2.2."""
    return [
        md(
            """
            ### Lab 2.2

            Three exercises. For each, replace every `raise NotImplementedError` in the stub,
            then run the check cell. Until then the checks print FAIL; that is expected. Three
            structural checks already pass on the stub ("mixin has no __init__" and "in the MRO"
            in exercise 2, "Report has no base class" in exercise 3): keep them passing.

            #### Exercise 1 — compute three MROs by hand

            The cell below defines three hierarchies. For each, work out the MRO **on paper**
            with `L[C] = C + merge(...)` (2.2.3), writing down every merge step, then make
            `predict_mro(case_name)` return your answer as a list of class names (ending with
            `"object"`). Do not call `__mro__` in your answer; the check compares it with
            `__mro__` for you.

            > **Note:** a failing check prints the real MRO. Finish all three on paper before
            > running it.
            """
        ),
        code(
            '''
            # Case "diamond"
            class Animal: ...


            class Swimmer(Animal): ...


            class Flyer(Animal): ...


            class Duck(Swimmer, Flyer): ...


            # Case "services"
            class Base: ...


            class LoggingMixin: ...


            class CacheMixin: ...


            class Service(LoggingMixin, CacheMixin, Base): ...


            class AuditMixin(LoggingMixin): ...


            class AuditedService(AuditMixin, Service): ...


            # Case "classic"
            class Persistent: ...


            class Versioned: ...


            class Searchable: ...


            class Document(Persistent, Versioned): ...


            class Index(Persistent, Searchable): ...


            class SearchableDocument(Document, Index): ...


            MRO_CASES: dict[str, type] = {
                "diamond": Duck,
                "services": AuditedService,
                "classic": SearchableDocument,
            }


            def predict_mro(case_name: str) -> list[str]:
                """Return the class names of the case's MRO, computed by hand."""
                raise NotImplementedError("Lab 2.2: write your three MROs in predict_mro")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    (case_name, lambda case_name=case_name: predict_mro(case_name), mro_names(cls))
                    for case_name, cls in MRO_CASES.items()
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — a JSON mixin for nested objects and datetimes

            Write `JsonMixin` with two methods and **no `__init__`**:

            - `to_dict()` returns the instance's attributes (from `vars(self)`) **except** names
              starting with `_`, with each value converted recursively:

              | Value | Becomes |
              | --- | --- |
              | another `JsonMixin` object | its `to_dict()` |
              | `datetime` or `date` | `isoformat()` string |
              | `Decimal` | `str(value)` |
              | `list` or `tuple` | a list of converted items |
              | `dict` | a dict with `str` keys and converted values |
              | anything else | unchanged |

            - `to_json(**dumps_options)` returns `json.dumps(self.to_dict(), **dumps_options)`.

            The sample classes in the cell after the stub use the mixin.
            """
        ),
        code(
            '''
            class JsonMixin:
                """Adds to_dict() / to_json() to any class whose state lives in instance attributes."""

                def to_dict(self) -> dict[str, Any]:
                    """Public attributes as JSON-ready values."""
                    raise NotImplementedError("Lab 2.2: implement JsonMixin.to_dict")

                def to_json(self, **dumps_options: Any) -> str:
                    """Serialize to_dict() with json.dumps."""
                    raise NotImplementedError("Lab 2.2: implement JsonMixin.to_json")
            '''
        ),
        md(
            """
            Sample classes (given): a `Customer` with nested `Address` and `LineItem` objects,
            a `datetime`, a `date`, a tuple, a dict holding another object, and a private
            `_password_hash` that must not be exported.
            """
        ),
        code(
            '''
            class Address(JsonMixin):
                """A postal address."""

                def __init__(self, city: str, pin_code: str) -> None:
                    self.city = city
                    self.pin_code = pin_code


            class LineItem(JsonMixin):
                """One purchased product."""

                def __init__(self, sku: str, unit_price: Decimal, quantity: int) -> None:
                    self.sku = sku
                    self.unit_price = unit_price
                    self.quantity = quantity


            class Customer(JsonMixin):
                """A customer with nested objects and a private field."""

                def __init__(
                    self,
                    name: str,
                    joined_at: datetime,
                    birthday: date,
                    addresses: list[Address],
                    last_order: list[LineItem],
                    tags: tuple[str, ...],
                    preferences: dict[str, object],
                ) -> None:
                    self.name, self.joined_at, self.birthday = name, joined_at, birthday
                    self.addresses, self.last_order = addresses, last_order
                    self.tags, self.preferences = tags, preferences
                    self._password_hash = "pbkdf2$not-for-json"


            def make_sample_customer() -> Customer:
                """A fresh customer for the checks."""
                return Customer(
                    name="Fatima",
                    joined_at=datetime(2026, 1, 15, 9, 30),
                    birthday=date(1994, 8, 2),
                    addresses=[Address("Pune", "411001"), Address("Goa", "403001")],
                    last_order=[LineItem("SOAP", Decimal("49.50"), 2)],
                    tags=("vip", "early-adopter"),
                    preferences={"newsletter": True, "home": Address("Pune", "411001")},
                )
            '''
        ),
        md("Run the checks."),
        code(
            '''
            EXPECTED_CUSTOMER_DICT = {
                "name": "Fatima",
                "joined_at": "2026-01-15T09:30:00",
                "birthday": "1994-08-02",
                "addresses": [{"city": "Pune", "pin_code": "411001"}, {"city": "Goa", "pin_code": "403001"}],
                "last_order": [{"sku": "SOAP", "unit_price": "49.50", "quantity": 2}],
                "tags": ["vip", "early-adopter"],
                "preferences": {"newsletter": True, "home": {"city": "Pune", "pin_code": "411001"}},
            }


            def address_with_landmark() -> dict[str, Any]:
                """to_dict() sees attributes added after __init__."""
                address = Address("Goa", "403001")
                address.landmark = "Fort"  # type: ignore[attr-defined]
                return address.to_dict()


            run_checks(
                [
                    ("to_dict", lambda: make_sample_customer().to_dict(), EXPECTED_CUSTOMER_DICT),
                    (
                        "private field skipped",
                        lambda: "_password_hash" in make_sample_customer().to_dict(),
                        False,
                    ),
                    (
                        "to_json round trip",
                        lambda: json.loads(make_sample_customer().to_json()),
                        EXPECTED_CUSTOMER_DICT,
                    ),
                    (
                        "dumps options forwarded",
                        lambda: Address("Pune", "411001").to_json(sort_keys=True, indent=None),
                        '{"city": "Pune", "pin_code": "411001"}',
                    ),
                    (
                        "indent forwarded",
                        lambda: Address("Goa", "403001").to_json(indent=2).splitlines()[1],
                        '  "city": "Goa",',
                    ),
                    (
                        "attributes added later",
                        address_with_landmark,
                        {"city": "Goa", "pin_code": "403001", "landmark": "Fort"},
                    ),
                    ("mixin has no __init__", lambda: "__init__" in JsonMixin.__dict__, False),
                    ("in the MRO", lambda: JsonMixin in Customer.__mro__, True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — refactor an inheritance tree into composition

            The legacy code below picks a report **format** by subclassing and adds
            **deliveries** (e-mail, archive) by subclassing again. It already needs five classes
            for three combinations, `EmailedTextReport` duplicates `EmailedCsvReport`, and an
            "archived text report" would need yet another class.

            Rewrite it with composition:

            - `CsvFormatter` and `TextFormatter`, each with `format(title, rows) -> str`
              producing exactly what `CsvReport.render` / `TextReport.render` produce.
            - `EmailDelivery(outbox)` and `ArchiveDelivery(archive)`, each with
              `deliver(title, content) -> None` doing what the legacy `publish` overrides do.
            - `Report(title, rows, formatter, deliveries=())` with no base class (other than
              `object`); `publish()` formats, calls every delivery **in order**, and returns
              the content. Store the deliveries as a list in `self.deliveries`.

            First, the legacy code (given, working).
            """
        ),
        code(
            '''
            type SalesRows = list[tuple[str, int]]

            SAMPLE_SALES: SalesRows = [("Soap", 120), ("Rice 5 kg", 45), ("Tea", 300)]


            class LegacyReport:
                """Legacy base: subclasses pick a format by overriding render()."""

                def __init__(self, title: str, rows: SalesRows) -> None:
                    self.title = title
                    self.rows = rows

                def render(self) -> str:
                    raise NotImplementedError  # subclasses override this

                def publish(self) -> str:
                    return self.render()


            class CsvReport(LegacyReport):
                def render(self) -> str:
                    body = "\\n".join(f"{product},{units}" for product, units in self.rows)
                    return f"# {self.title}\\nproduct,units\\n{body}"


            class TextReport(LegacyReport):
                def render(self) -> str:
                    lines = [self.title, "=" * len(self.title)]
                    lines += [f"{product:<12}{units:>5}" for product, units in self.rows]
                    return "\\n".join(lines)
            '''
        ),
        md("The legacy delivery subclasses (given):"),
        code(
            """
            class EmailedCsvReport(CsvReport):
                def __init__(self, title: str, rows: SalesRows, outbox: list[tuple[str, str]]) -> None:
                    super().__init__(title, rows)
                    self.outbox = outbox

                def publish(self) -> str:
                    content = super().publish()
                    self.outbox.append((self.title, content))
                    return content


            class EmailedTextReport(TextReport):  # the same code as EmailedCsvReport, duplicated
                def __init__(self, title: str, rows: SalesRows, outbox: list[tuple[str, str]]) -> None:
                    super().__init__(title, rows)
                    self.outbox = outbox

                def publish(self) -> str:
                    content = super().publish()
                    self.outbox.append((self.title, content))
                    return content


            class ArchivedEmailedCsvReport(EmailedCsvReport):
                def __init__(
                    self, title: str, rows: SalesRows, outbox: list[tuple[str, str]], archive: dict[str, str]
                ) -> None:
                    super().__init__(title, rows, outbox)
                    self.archive = archive

                def publish(self) -> str:
                    content = super().publish()
                    self.archive[self.title] = content
                    return content


            print(TextReport("Weekly sales", SAMPLE_SALES).publish())
            """
        ),
        md("Your composition-based version:"),
        code(
            '''
            class CsvFormatter:
                def format(self, title: str, rows: SalesRows) -> str:
                    """Same output as CsvReport.render."""
                    raise NotImplementedError("Lab 2.2: implement CsvFormatter.format")


            class TextFormatter:
                def format(self, title: str, rows: SalesRows) -> str:
                    """Same output as TextReport.render."""
                    raise NotImplementedError("Lab 2.2: implement TextFormatter.format")


            class EmailDelivery:
                def __init__(self, outbox: list[tuple[str, str]]) -> None:
                    raise NotImplementedError("Lab 2.2: implement EmailDelivery")

                def deliver(self, title: str, content: str) -> None:
                    raise NotImplementedError("Lab 2.2: implement EmailDelivery.deliver")


            class ArchiveDelivery:
                def __init__(self, archive: dict[str, str]) -> None:
                    raise NotImplementedError("Lab 2.2: implement ArchiveDelivery")

                def deliver(self, title: str, content: str) -> None:
                    raise NotImplementedError("Lab 2.2: implement ArchiveDelivery.deliver")


            class Report:
                def __init__(
                    self, title: str, rows: SalesRows, formatter: Any, deliveries: Iterable[Any] = ()
                ) -> None:
                    raise NotImplementedError("Lab 2.2: implement Report")

                def publish(self) -> str:
                    raise NotImplementedError("Lab 2.2: implement Report.publish")
            '''
        ),
        md(
            """
            Run the checks. They compare every output and side effect with the legacy classes.
            """
        ),
        code(
            '''
            def legacy_outputs() -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
                """Publish through the legacy tree and capture every side effect."""
                outbox: list[tuple[str, str]] = []
                archive: dict[str, str] = {}
                text_content = EmailedTextReport("Weekly sales", SAMPLE_SALES, outbox).publish()
                csv_content = ArchivedEmailedCsvReport("Weekly sales", SAMPLE_SALES, outbox, archive).publish()
                return text_content, csv_content, outbox, archive


            def composed_outputs() -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
                """Publish the same two reports through Report + formatters + deliveries."""
                outbox: list[tuple[str, str]] = []
                archive: dict[str, str] = {}
                text_content = Report(
                    "Weekly sales", SAMPLE_SALES, TextFormatter(), [EmailDelivery(outbox)]
                ).publish()
                csv_deliveries = [EmailDelivery(outbox), ArchiveDelivery(archive)]
                csv_content = Report("Weekly sales", SAMPLE_SALES, CsvFormatter(), csv_deliveries).publish()
                return text_content, csv_content, outbox, archive


            def new_combination() -> tuple[str, dict[str, str]]:
                """Archived text report: a combination the legacy tree has no class for."""
                archive: dict[str, str] = {}
                content = Report("Stock", [("Tea", 7)], TextFormatter(), [ArchiveDelivery(archive)]).publish()
                return content, archive


            run_checks(
                [
                    (
                        "plain CSV",
                        lambda: Report("Q3", SAMPLE_SALES, CsvFormatter()).publish(),
                        CsvReport("Q3", SAMPLE_SALES).publish(),
                    ),
                    (
                        "plain text",
                        lambda: Report("Q3", SAMPLE_SALES, TextFormatter()).publish(),
                        TextReport("Q3", SAMPLE_SALES).publish(),
                    ),
                    ("same side effects as legacy", composed_outputs, legacy_outputs()),
                    (
                        "new combination, no new class",
                        new_combination,
                        ("Stock\\n=====\\nTea             7", {"Stock": "Stock\\n=====\\nTea             7"}),
                    ),
                    ("Report has no base class", lambda: Report.__bases__, (object,)),
                    ("deliveries default to none", lambda: Report("Q3", [], CsvFormatter()).deliveries, []),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.2."""
    return [
        md(
            """
            ### Recap — Unit 2.2

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Overriding | A subclass method replaces the base one; `self.method()` dispatches on the instance's class | method overriding |
            | Extending | Call the original with `super().method(...)`; forgetting `super().__init__` fails silently | `super.method()` |
            | `@override` | Marks intent; type checkers catch typos (3.12+) | TS `override` |
            | `isinstance` / `issubclass` | Follow the MRO; accept tuples and `A | B` | `instanceof` |
            | `object` | The root of every class; source of default dunders | `Object.prototype` |
            | Zero-arg `super()` | Reads the hidden `__class__` cell and the first argument | `[[HomeObject]]` |
            | Next in MRO | `super()` can reach a sibling under multiple inheritance | — (always the static parent) |
            | Cooperative `**kwargs` | Keyword-only args, take yours, pass the rest, `object` gets nothing | — |
            | C3 MRO | `L[C] = C + merge(...)`; take the first head not in any tail | prototype chain |
            | Inconsistent MRO | Base listed before its subclass, or conflicting orders → `TypeError` | — |
            | Mixins | One capability each, mixins left, main base right | `Object.assign`, class-factory mixins |
            | Composition | Has-a + delegation; wrappers combine features additively | object composition |
            | Liskov | Subclasses must keep the base class's promises (Square/Rectangle) | same |
            | SOLID | S, O, L, I, D: small focused classes, plug-in extension, injected dependencies | same |

            **Further reading**

            - [Tutorial: inheritance](https://docs.python.org/3/tutorial/classes.html#inheritance),
              [multiple inheritance](https://docs.python.org/3/tutorial/classes.html#multiple-inheritance)
            - [`super`](https://docs.python.org/3/library/functions.html#super),
              [`isinstance`](https://docs.python.org/3/library/functions.html#isinstance),
              [`issubclass`](https://docs.python.org/3/library/functions.html#issubclass),
              [`typing.override`](https://docs.python.org/3/library/typing.html#typing.override)
            - [The Python 2.3 Method Resolution Order](https://docs.python.org/3/howto/mro.html)
              (the C3 algorithm, with worked examples)
            - [`socketserver` mix-in classes](https://docs.python.org/3/library/socketserver.html#server-objects),
              [`__getattr__`](https://docs.python.org/3/reference/datamodel.html#object.__getattr__)
            - [PEP 3135 — New `super`](https://peps.python.org/pep-3135/),
              [PEP 698 — `@override`](https://peps.python.org/pep-0698/),
              [PEP 253 — Subtyping built-in types](https://peps.python.org/pep-0253/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.2 and Lab 2.2."""
    return [
        *_overview_cells(),
        *_single_inheritance_cells(),
        *_super_cells(),
        *_mro_cells(),
        *_mixin_cells(),
        *_composition_cells(),
        *_solid_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
