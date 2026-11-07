"""Unit 2.6 — Dataclasses, Enums and Pythonic Design Patterns (with Lab 2.6)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import copy
import dataclasses
import functools
import importlib.util
import inspect
import json
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import (
    KW_ONLY,
    FrozenInstanceError,
    InitVar,
    asdict,
    astuple,
    dataclass,
    field,
    fields,
    replace,
)
from datetime import date
from decimal import Decimal
from enum import Enum, Flag, IntEnum, IntFlag, StrEnum, auto, unique
from typing import Any, NamedTuple, NotRequired, Protocol, ReadOnly, Required, TypedDict


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


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 2.6 — Dataclasses, Enums and Pythonic Design Patterns

            **Objectives**

            - Generate `__init__`, `__repr__`, `__eq__` (and more) with `@dataclass`, and control
              each field with `field()`.
            - Choose between a dataclass, `NamedTuple`, `TypedDict`, a plain class, Pydantic and
              attrs.
            - Describe JSON-shaped dicts with `TypedDict` (`Required`, `NotRequired`,
              `ReadOnly`).
            - Model fixed sets of values with `Enum`, `IntEnum`, `StrEnum`, `Flag` and `IntFlag`.
            - Recognize nine classic design patterns and write their Pythonic forms.
            - Tell value objects from entities and model each correctly.

            **JS / TS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `class` with a hand-written constructor | `@dataclass` | Fields are declared once, with types; methods are generated |
            | `Object.freeze(obj)` | `@dataclass(frozen=True)` | Frozen dataclasses are also **hashable** (usable as dict keys) |
            | `{...obj, city: "Pune"}` | `dataclasses.replace(obj, city="Pune")` | Runs `__init__` and validation again |
            | TS `type User = {name: string; age?: number}` | `class User(TypedDict): name: str; age: NotRequired[int]` | Erased at run time: just a `dict` |
            | TS `readonly` property | `ReadOnly[...]` in a TypedDict, or `frozen=True` | `ReadOnly` is checked only by type checkers |
            | TS `enum Status { Paid = "paid" }` | `class Status(StrEnum): PAID = "paid"` | Members are singletons; `Status("paid")` looks one up |
            | Bit flags with `\\|` on numbers | `Flag` / `IntFlag` | Named members, `in` for membership, readable repr |
            | Design patterns from Java/C# books | functions, modules, Protocols | Many patterns shrink to a few lines in Python |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _dataclass_basics_cells() -> list[NotebookNode]:
    """2.6.1 @dataclass: generated methods and field() options."""
    return [
        md(
            """
            ### 2.6.1 `@dataclass`

            A class for "a bundle of named values" needs the same three methods every time.
            Written by hand, the field names appear four times:
            """
        ),
        code(
            """
            class HandWrittenProduct:
                def __init__(self, name: str, price: Decimal, in_stock: bool = True) -> None:
                    self.name, self.price, self.in_stock = name, price, in_stock

                def __repr__(self) -> str:
                    fields_text = f"name={self.name!r}, price={self.price!r}, in_stock={self.in_stock!r}"
                    return f"HandWrittenProduct({fields_text})"

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, HandWrittenProduct):
                        return NotImplemented
                    return (self.name, self.price, self.in_stock) == (other.name, other.price, other.in_stock)


            print(HandWrittenProduct("pen", Decimal("10")))
            """
        ),
        md(
            """
            **Generated methods.** `@dataclass` reads the class annotations (in order) and
            writes `__init__`, `__repr__` and `__eq__` for you, plus `__match_args__` for
            `match` (Unit 1.8.4). Because it defines `__eq__`, the class is unhashable by
            default (Unit 2.4.3) unless it is frozen.
            """
        ),
        code(
            """
            @dataclass
            class Product:
                name: str
                price: Decimal
                in_stock: bool = True


            pen = Product("pen", Decimal("10"))
            print(pen)
            print(f"{pen == Product('pen', Decimal('10'))=}, {inspect.signature(Product)=}")
            print(f"{Product.__match_args__=}, {Product.__hash__ is None=}")
            match pen:
                case Product(name, price, in_stock=True):
                    print(f"matched {name} at {price}")
            """
        ),
        md(
            """
            #### `field()` options

            Each field can be tuned with `field(...)`:

            | Option | Effect |
            | --- | --- |
            | `default` / `default_factory` | default value / zero-argument function called for each instance |
            | `repr=False` | leave the field out of `__repr__` |
            | `compare=False` | leave the field out of `__eq__` and ordering (and the hash) |
            | `init=False` | not an `__init__` parameter; set it in `__post_init__` or via a default |
            | `kw_only=True` | keyword-only parameter in `__init__` |
            | `metadata={...}` | read-only mapping for your own tools (validators, serializers) |
            | `doc="..."` | docstring for the field (*New in 3.14*) |

            **`default_factory`.** A mutable default would be shared by every instance (the
            same trap as mutable default arguments, Unit 1.10.5), so dataclasses refuse `list`,
            `dict` and `set` defaults. `default_factory=list` calls `list()` per instance.
            """
        ),
        code(
            """
            def define_shared_default() -> type:
                @dataclass
                class Basket:
                    items: list[str] = []  # the trap being refused

                return Basket


            @dataclass
            class Basket:
                owner: str
                items: list[str] = field(default_factory=list)


            print(raised_message(define_shared_default))
            first_basket, second_basket = Basket("asha"), Basket("ravi")
            first_basket.items.append("tea")
            print(f"{first_basket=}, {second_basket=}")
            """
        ),
        md(
            """
            **`repr=False`** hides a field from `__repr__`: useful for secrets and for huge values
            that would flood logs.
            """
        ),
        code(
            """
            @dataclass
            class ApiCredentials:
                client_id: str
                client_secret: str = field(repr=False)


            print(ApiCredentials("shop-app", "s3cr3t-value"))
            """
        ),
        md(
            """
            **`compare=False`** leaves a field out of equality (and ordering and hashing). A
            cache or a "last seen" timestamp should not make two otherwise identical objects
            unequal.
            """
        ),
        code(
            """
            @dataclass
            class SearchQuery:
                text: str
                page: int = 1
                executed_at: date | None = field(default=None, compare=False)


            print(f"{SearchQuery('tea', 1, date(2026, 1, 1)) == SearchQuery('tea', 1, date(2026, 6, 1))=}")
            print(f"{SearchQuery('tea', 1) == SearchQuery('tea', 2)=}")
            """
        ),
        md(
            """
            **`init=False`** removes a field from `__init__`. Give it a default, or compute it in
            `__post_init__` (shown below). Here a running line number comes from a factory.
            """
        ),
        code(
            """
            line_numbers = iter(range(1, 1_000))


            @dataclass
            class InvoiceLine:
                description: str
                amount: Decimal
                line_number: int = field(init=False, default_factory=lambda: next(line_numbers))


            print(InvoiceLine("Tea 500 g", Decimal("240")), InvoiceLine("Mug", Decimal("199")))
            print(f"{list(inspect.signature(InvoiceLine).parameters)=}")
            print(raised_error_name(lambda: InvoiceLine("x", Decimal(1), line_number=9)))
            """
        ),
        md(
            """
            **`kw_only=True` on one field** makes that parameter keyword-only, which also lets a
            field without a default follow one with a default (keyword-only parameters are
            exempt from the ordering rule).
            """
        ),
        code(
            """
            @dataclass
            class Coupon:
                code: str
                percent: int = 10
                expires: date = field(kw_only=True)


            print(Coupon("DIWALI", expires=date(2026, 11, 10)))
            print(f"{inspect.signature(Coupon)=}")
            print(raised_error_name(lambda: Coupon("DIWALI", 10, date(2026, 11, 10))))
            """
        ),
        md(
            """
            **`metadata`** attaches your own information to a field; dataclasses never read it,
            but your code can, through `fields()`. This is how serializers and form libraries
            attach units, labels or validation rules. **`doc`** (*New in 3.14*) documents a
            field.
            """
        ),
        code(
            """
            @dataclass
            class Parcel:
                weight: float = field(metadata={"unit": "kg", "max": 30}, doc="Gross weight.")
                length: float = field(metadata={"unit": "cm"})


            for parcel_field in fields(Parcel):
                print(f"{parcel_field.name}: {dict(parcel_field.metadata)}")
            if sys.version_info >= (3, 14):
                print(f"{fields(Parcel)[0].doc=}")
            """
        ),
    ]


def _dataclass_options_cells() -> list[NotebookNode]:
    """2.6.1 class options, __post_init__, InitVar, helpers and inheritance."""
    return [
        md(
            """
            #### Class options: `frozen`, `order`, `slots`, `kw_only`

            **`frozen=True`** makes assignment raise `FrozenInstanceError` (a subclass of
            `AttributeError`) and, because the fields can no longer change, generates
            `__hash__`: frozen dataclasses work as dict keys and set members.
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class GeoPoint:
                latitude: float
                longitude: float


            pune = GeoPoint(18.52, 73.86)
            print(raised_message(lambda: set_attribute(pune, "latitude", 0.0)))
            print(f"{issubclass(FrozenInstanceError, AttributeError)=}")
            print(f"{ {pune: 'Pune'}[GeoPoint(18.52, 73.86)]=}")
            """
        ),
        md(
            """
            **`order=True`** generates `<`, `<=`, `>`, `>=` that compare fields **as a tuple, in
            definition order**, so put the most significant field first.
            """
        ),
        code(
            """
            @dataclass(order=True)
            class Release:
                major: int
                minor: int
                name: str = field(compare=False)


            releases = [Release(3, 15, "latest"), Release(3, 9, "old"), Release(3, 13, "previous")]
            print([release.name for release in sorted(releases)])
            print(f"{Release(3, 9, 'a') < Release(3, 13, 'b')=}")
            print(raised_error_name(lambda: Release(3, 9, "a") < (3, 13)))
            """
        ),
        md(
            """
            **`slots=True`** (3.10+) builds the class again with `__slots__` (Unit 2.5.5): less
            memory, no stray attributes. **`kw_only=True`** on the class makes every field
            keyword-only; the `KW_ONLY` marker does the same for the fields after it.
            """
        ),
        code(
            """
            @dataclass(slots=True)
            class Pixel:
                x: int
                y: int


            @dataclass(kw_only=True)
            class RetryPolicy:
                attempts: int = 3
                backoff_seconds: float = 0.5


            @dataclass
            class Upload:
                path: str
                _: KW_ONLY
                overwrite: bool = False
                public: bool = False


            print(f"{Pixel.__slots__=}, {hasattr(Pixel(1, 2), '__dict__')=}")
            print(raised_message(lambda: set_attribute(Pixel(1, 2), "colour", "red")))
            print(f"{inspect.signature(RetryPolicy)=}")
            print(f"{inspect.signature(Upload)=}")
            """
        ),
        md(
            """
            #### `__post_init__` and `InitVar`

            The generated `__init__` calls `__post_init__()` at the end: the place for
            validation and normalization. In a **frozen** class, assign with
            `object.__setattr__` (the generated `__init__` does the same).
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class EmailAddress:
                value: str

                def __post_init__(self) -> None:
                    cleaned = self.value.strip().lower()
                    if cleaned.count("@") != 1:
                        raise ValueError(f"invalid email address: {self.value!r}")
                    object.__setattr__(self, "value", cleaned)


            print(EmailAddress("  Asha@Example.COM "))
            print(raised_message(lambda: EmailAddress("asha.example.com")))
            """
        ),
        md(
            """
            An **`InitVar`** is an `__init__` parameter that is **not** stored as a field; it is
            passed to `__post_init__` instead. Typical use: a raw input you transform and then
            throw away, like a plain-text password.
            """
        ),
        code(
            """
            import hashlib


            @dataclass
            class UserAccount:
                username: str
                password: InitVar[str]
                password_digest: str = field(init=False, repr=False)

                def __post_init__(self, password: str) -> None:
                    if len(password) < 8:
                        raise ValueError("password must be at least 8 characters")
                    self.password_digest = hashlib.sha256(password.encode()).hexdigest()


            account = UserAccount("asha", "correct horse")
            print(account, f"{len(account.password_digest)=}")
            print(f"{[account_field.name for account_field in fields(UserAccount)]=}  (no password)")
            print(raised_message(lambda: UserAccount("ravi", "short")))
            """
        ),
        md(
            """
            #### `asdict`, `astuple`, `replace`, `fields`

            `asdict` and `astuple` convert **recursively** (nested dataclasses, lists and dicts
            inside), deep-copying as they go, so the result shares nothing with the object.
            """
        ),
        code(
            """
            @dataclass
            class Address:
                city: str
                pin_code: str


            @dataclass
            class Customer:
                name: str
                addresses: list[Address] = field(default_factory=list)


            asha = Customer("Asha", [Address("Pune", "411001")])
            as_dict = asdict(asha)
            print(f"{as_dict=}")
            print(f"{astuple(asha)=}")
            as_dict["addresses"][0]["city"] = "Mumbai"
            print(f"{asha.addresses[0].city=}  (unchanged: asdict deep-copies)")
            print(json.dumps(as_dict))
            """
        ),
        md(
            """
            `replace(obj, **changes)` returns a **new** object with some fields changed; it
            calls `__init__`, so `__post_init__` validation runs again. Since 3.13 the generic
            `copy.replace` does the same for dataclasses, named tuples, dates and more
            (*New in 3.13*). `fields()` lists the `Field` objects, which is how generic code
            (serializers, `asdict` itself) walks a dataclass.
            """
        ),
        code(
            """
            work_email = EmailAddress("asha@example.com")
            print(f"{replace(work_email, value='ASHA@shop.in')=}")
            print(raised_message(lambda: replace(work_email, value="not-an-email")))
            if sys.version_info >= (3, 13):
                print(f"{copy.replace(pune, longitude=0.0)=}")
            print([(customer_field.name, customer_field.type) for customer_field in fields(Customer)])
            """
        ),
        md(
            """
            #### Inheritance rules

            A dataclass subclass collects fields from its bases first (in MRO order), then adds
            its own. Redefining a field keeps its **original position** but takes the new
            default. Because `__init__` parameters follow field order, a base field **with** a
            default followed by a subclass field **without** one is an error; `kw_only` (or a
            default) fixes it.
            """
        ),
        code(
            """
            @dataclass
            class Item:
                sku: str
                quantity: int = 1


            @dataclass
            class GiftItem(Item):
                quantity: int = 2  # redefined: same position, new default
                message: str = ""


            def define_bad_subclass() -> type:
                @dataclass
                class FragileItem(Item):
                    handling_note: str  # no default after a defaulted base field

                return FragileItem


            @dataclass
            class FragileItem(Item):
                handling_note: str = field(kw_only=True)


            print(f"{inspect.signature(GiftItem)=}")
            print(raised_message(define_bad_subclass))
            print(FragileItem("VASE-1", handling_note="this side up"))
            """
        ),
        md(
            """
            #### Under the hood: what `@dataclass` stores

            The decorator records its options in `__dataclass_params__` and every field in
            `__dataclass_fields__`. `eq`, `frozen` and `unsafe_hash` together decide
            `__hash__`:

            | `eq` | `frozen` | `unsafe_hash` | `__hash__` |
            | --- | --- | --- | --- |
            | `True` (default) | `False` | `False` | `None` (unhashable) |
            | `True` | `True` | `False` | generated from the compared fields |
            | `False` | any | `False` | inherited (identity) |
            | any | any | `True` | generated even though mutable (dangerous, Unit 2.4.3) |
            """
        ),
        code(
            """
            print(f"{GeoPoint.__dataclass_params__}")
            print(f"{list(GeoPoint.__dataclass_fields__)=}")
            for point_class in (Product, GeoPoint):
                print(f"{point_class.__name__}: {point_class.__hash__ is None=}")
            print(f"{dataclasses.is_dataclass(pune)=}, {dataclasses.is_dataclass(HandWrittenProduct)=}")
            """
        ),
    ]


def _record_comparison_cells() -> list[NotebookNode]:
    """2.6.2 Record-type comparison."""
    return [
        md(
            """
            ### 2.6.2 Record-type comparison

            Six ways to hold "a book with a title and a price":

            | | dataclass | `NamedTuple` | `TypedDict` | plain class | Pydantic `BaseModel` | attrs |
            | --- | --- | --- | --- | --- | --- | --- |
            | Runtime type | your class | a `tuple` subclass | plain `dict` | your class | your class | your class |
            | Generated `__init__` / `repr` / `eq` | yes | yes | no (dict literal) | no | yes | yes |
            | Mutable | yes (or `frozen`) | no | yes | yes | yes (or frozen) | yes (or frozen) |
            | Validation at run time | only what you write | no | no | what you write | **yes**, with conversion | optional validators |
            | Memory | `__dict__` (or `slots=True`) | tuple: small | dict | `__dict__` | larger | slots by default |
            | Unpacking / indexing | no | yes (`title, price = book`) | by key | no | no | no |
            | Dependency | stdlib | stdlib | stdlib | — | third party | third party |
            | Best for | internal domain objects | small immutable records, tuple APIs | JSON-shaped data you pass along | full control / custom behaviour | data from outside (APIs, config) | dataclass++ (validators, converters) |

            Each one in code, same data:
            """
        ),
        code(
            """
            @dataclass
            class BookDataclass:
                title: str
                price: Decimal


            book = BookDataclass("Clean Code", Decimal("499"))
            book.price = Decimal("449")  # mutable unless frozen=True
            print(f"dataclass:  {book}")
            """
        ),
        md("`NamedTuple`: immutable, indexable, unpackable, and equal to a plain tuple."),
        code(
            """
            class BookTuple(NamedTuple):
                title: str
                price: Decimal


            tuple_book = BookTuple("Clean Code", Decimal("499"))
            title, price = tuple_book
            print(
                f"NamedTuple: {tuple_book}, {tuple_book[0]=}, {tuple_book == ('Clean Code', Decimal('499'))=}"
            )
            print(raised_error_name(lambda: set_attribute(tuple_book, "price", Decimal(1))))
            """
        ),
        md("`TypedDict`: a type annotation for a plain `dict` (details in 2.6.3)."),
        code(
            """
            class BookDict(TypedDict):
                title: str
                price: str


            dict_book: BookDict = {"title": "Clean Code", "price": "499"}
            print(f"TypedDict:  {dict_book}, {type(dict_book).__name__=}")
            """
        ),
        md("A plain class: you write everything, so you control everything."),
        code(
            """
            class BookPlain:
                def __init__(self, title: str, price: Decimal) -> None:
                    self.title, self.price = title, price


            plain_book = BookPlain("Clean Code", Decimal("499"))
            same_data_book = BookPlain("Clean Code", Decimal("499"))
            print(f"plain:      {plain_book.title}, {plain_book == same_data_book=}  (identity)")
            """
        ),
        md(
            """
            Pydantic validates and **converts** at run time (`"499"` becomes `Decimal("499")`).
            It is a Phase 6 dependency, so the cell checks first and shows the code it would
            run.
            """
        ),
        code(
            """
            if importlib.util.find_spec("pydantic") is None:
                print("pydantic not installed: skipping (Phase 6 installs it). The code would be:")
                print("    class BookModel(BaseModel):\\n        title: str\\n        price: Decimal")
                print('    BookModel(title="Clean Code", price="499")  # price converted to Decimal')
            else:
                from pydantic import BaseModel

                class BookModel(BaseModel):
                    title: str
                    price: Decimal

                print(f"pydantic:   {BookModel(title='Clean Code', price='499')!r}")
            """
        ),
        md(
            """
            attrs is the project dataclasses were modelled on. It happens to be installed here
            (other tools depend on it), but it is not a course dependency, so the cell still
            checks.
            """
        ),
        code(
            """
            if importlib.util.find_spec("attrs") is None:
                print("attrs not installed: skipping")
            else:
                import attrs

                @attrs.define
                class BookAttrs:
                    title: str
                    price: Decimal = attrs.field(validator=attrs.validators.instance_of(Decimal))

                print(f"attrs:      {BookAttrs('Clean Code', Decimal('499'))}")
                print(f"            {raised_error_name(lambda: BookAttrs('Clean Code', 499))}  (validator)")
            """
        ),
    ]


def _typeddict_cells() -> list[NotebookNode]:
    """2.6.3 TypedDict."""
    return [
        md(
            """
            ### 2.6.3 `TypedDict`

            A `TypedDict` describes the **keys and value types of a dict** for type checkers,
            like a TypeScript object type. At run time it is a plain `dict`: no class instance,
            no validation, no methods. Use it for JSON payloads you read and pass along.
            """
        ),
        code(
            """
            class OrderPayload(TypedDict):
                order_id: str
                amount_paise: int
                coupon: NotRequired[str]


            payload: OrderPayload = {"order_id": "ORD-1", "amount_paise": 49_900}
            print(f"{type(payload) is dict=}, {payload=}")
            wrong_payload: OrderPayload = {"order_id": 7}  # type: ignore[typeddict-item]
            print(f"{wrong_payload=}  (no run-time check: a type checker reports this line)")
            print(raised_message(lambda: isinstance(payload, OrderPayload)))
            """
        ),
        md(
            """
            **`total=False`** makes every key optional; **`Required[...]`** marks the exceptions.
            **`NotRequired[...]`** does the opposite in a total TypedDict. The class records
            the result in `__required_keys__` and `__optional_keys__`.
            """
        ),
        code(
            '''
            class ProductPatch(TypedDict, total=False):
                """A PATCH body: send only what changes, but the SKU is always required."""

                sku: Required[str]
                name: str
                price_paise: int


            patch: ProductPatch = {"sku": "PEN-01", "price_paise": 1_200}
            print(f"{sorted(ProductPatch.__required_keys__)=}")
            print(f"{sorted(ProductPatch.__optional_keys__)=}")
            print(f"{sorted(OrderPayload.__required_keys__)=}, {sorted(OrderPayload.__optional_keys__)=}")
            '''
        ),
        md(
            """
            **`ReadOnly[...]`** (*New in 3.13*, PEP 705) marks keys that must not be changed
            through this type; again only type checkers enforce it, recorded in
            `__readonly_keys__`.
            """
        ),
        code(
            """
            class AuditedRecord(TypedDict):
                record_id: ReadOnly[str]
                note: str


            audited: AuditedRecord = {"record_id": "REC-9", "note": "draft"}
            audited["record_id"] = "REC-10"  # type: ignore[typeddict-readonly-mutated]
            print(f"{audited=}  (a type checker reports the assignment; Python does not)")
            if sys.version_info >= (3, 13):
                print(f"{AuditedRecord.__readonly_keys__=}, {AuditedRecord.__mutable_keys__=}")
            """
        ),
        md(
            """
            > **Note:** a type checker (mypy, pyright; Phase 4) is what makes `TypedDict` useful.
            > To **validate** incoming JSON at run time, use a dataclass with `__post_init__` or
            > Pydantic (Phase 6).
            """
        ),
    ]


def _enum_cells() -> list[NotebookNode]:
    """2.6.4 Enums."""
    return [
        md(
            """
            ### 2.6.4 Enums

            An **enum** is a class whose members are a fixed set of named singletons. Members
            have a `name` and a `value`, compare by identity, and the class is iterable (its
            metaclass `EnumType` provides `__iter__` / `__len__`, Unit 2.5.7).
            """
        ),
        code(
            """
            class ShippingSpeed(Enum):
                STANDARD = 1
                EXPRESS = 2
                SAME_DAY = 3


            print(f"{ShippingSpeed.EXPRESS=}, {ShippingSpeed.EXPRESS.name=}, {ShippingSpeed.EXPRESS.value=}")
            print(f"{list(ShippingSpeed)=}")
            print(f"{len(ShippingSpeed)=}, {ShippingSpeed.EXPRESS is ShippingSpeed.EXPRESS=}")
            print(f"{ShippingSpeed.EXPRESS == 2=}  (a plain Enum never equals its value)")
            """
        ),
        md(
            """
            **`auto()`** picks values for you: 1, 2, 3, … for `Enum`, the lower-cased name for
            `StrEnum`, powers of two for `Flag`.
            """
        ),
        code(
            """
            class TicketPriority(Enum):
                LOW = auto()
                MEDIUM = auto()
                HIGH = auto()


            print([(priority.name, priority.value) for priority in TicketPriority])
            """
        ),
        md(
            """
            **Lookup by value and by name.** `Enum(value)` finds the member with that value
            (`ValueError` if none); `Enum[name]` finds it by name (`KeyError`). This is how you
            turn database values or URL parameters back into members.
            """
        ),
        code(
            """
            print(f"{ShippingSpeed(2)=}, {ShippingSpeed['SAME_DAY']=}")
            print(raised_message(lambda: ShippingSpeed(9)))
            print(raised_message(lambda: ShippingSpeed["OVERNIGHT"]))
            print(f"{ShippingSpeed.__members__.keys()=}")
            """
        ),
        md(
            """
            **`IntEnum`** members **are** ints: they compare with and do arithmetic like ints,
            useful when an API or a C library expects numbers. `http.HTTPStatus` is the
            standard library's example.
            """
        ),
        code(
            """
            from http import HTTPStatus


            class RetryLimit(IntEnum):
                NONE = 0
                FEW = 3
                MANY = 10


            print(f"{RetryLimit.FEW == 3=}, {RetryLimit.FEW + 1=}")
            print(f"{sorted([RetryLimit.MANY, 5, RetryLimit.FEW])=}")
            print(f"{HTTPStatus(404)=}, {HTTPStatus.NOT_FOUND.phrase=}, {HTTPStatus.NOT_FOUND == 404=}")
            """
        ),
        md(
            """
            **`StrEnum`** (3.11) members are strings: they compare equal to their value, format
            as the value, and serialize to JSON with no custom encoder. `auto()` gives the
            lower-cased name.
            """
        ),
        code(
            """
            class DeployEnvironment(StrEnum):
                DEVELOPMENT = auto()
                STAGING = auto()
                PRODUCTION = auto()


            print(f"{DeployEnvironment.STAGING == 'staging'=}, {DeployEnvironment.STAGING.upper()=}")
            print(f"deploying to {DeployEnvironment.PRODUCTION}")
            print(json.dumps({"environment": DeployEnvironment.PRODUCTION}))
            """
        ),
        md(
            """
            **`Flag`** members combine with `|`, `&`, `^` and `~`; `in` tests whether bits are
            set, and iterating a combination yields its single-bit members (3.11+).
            """
        ),
        code(
            """
            class TextStyle(Flag):
                BOLD = auto()
                ITALIC = auto()
                UNDERLINE = auto()


            heading_style = TextStyle.BOLD | TextStyle.UNDERLINE
            print(f"{heading_style=}, {TextStyle.BOLD in heading_style=}, {TextStyle.ITALIC in heading_style=}")
            print(f"{list(heading_style)=}, {heading_style & ~TextStyle.BOLD=}")
            print(f"{bool(TextStyle(0))=}  (no flags set is falsy)")
            """
        ),
        md(
            """
            **`IntFlag`** is a `Flag` that is also an `int`, for bit masks that cross into
            numeric APIs, such as Unix file modes.
            """
        ),
        code(
            """
            class FileMode(IntFlag):
                EXECUTE = 0o1
                WRITE = 0o2
                READ = 0o4


            read_write = FileMode.READ | FileMode.WRITE
            print(f"{read_write=}, {int(read_write)=}, {read_write == 6=}")
            print(f"{FileMode(7)=}, {oct(FileMode.READ | FileMode.EXECUTE)=}")
            """
        ),
        md(
            """
            **`@unique`.** Two members with the same value are allowed: the second becomes an
            **alias** of the first (handy for legacy names). `@unique` turns that into an error
            when aliases would be a mistake.
            """
        ),
        code(
            """
            class PaymentMethod(Enum):
                CARD = "card"
                UPI = "upi"
                CREDIT_CARD = "card"  # alias of CARD


            def define_unique_enum() -> type:
                @unique
                class StrictPaymentMethod(Enum):
                    CARD = "card"
                    CREDIT_CARD = "card"

                return StrictPaymentMethod


            print(f"{PaymentMethod.CREDIT_CARD is PaymentMethod.CARD=}, {list(PaymentMethod)=}")
            print(f"{list(PaymentMethod.__members__)=}  (aliases are listed here)")
            print(raised_message(define_unique_enum))
            """
        ),
        md(
            """
            **Methods on enums.** Enums are classes, so members can have methods, properties
            and class methods. Keeping behaviour next to the values avoids `if/elif` chains
            scattered through the code.
            """
        ),
        code(
            """
            class DeliverySlot(Enum):
                STANDARD = ("Standard", 5, Decimal("40"))
                EXPRESS = ("Express", 2, Decimal("99"))

                def __init__(self, label: str, days: int, fee: Decimal) -> None:
                    self.label, self.days, self.fee = label, days, fee

                def arrives_by(self, ordered_on: date) -> date:
                    return date.fromordinal(ordered_on.toordinal() + self.days)

                @classmethod
                def fastest(cls) -> DeliverySlot:
                    return min(cls, key=lambda slot: slot.days)


            print(f"{DeliverySlot.EXPRESS.label=}, {DeliverySlot.EXPRESS.fee=}")
            print(f"{DeliverySlot.STANDARD.arrives_by(date(2026, 11, 7))=}")
            print(f"{DeliverySlot.fastest()=}")
            """
        ),
        md(
            """
            **Enums in `match`.** A dotted name such as `ShippingSpeed.EXPRESS` is a **value
            pattern** (compared with `==`), not a capture, so enums read naturally in `match`.
            """
        ),
        code(
            """
            def shipping_message(speed: ShippingSpeed) -> str:
                match speed:
                    case ShippingSpeed.SAME_DAY:
                        return "arrives tonight"
                    case ShippingSpeed.EXPRESS:
                        return "arrives in 2 days"
                    case _:
                        return "arrives within a week"


            print([shipping_message(speed) for speed in ShippingSpeed])
            """
        ),
        md(
            """
            **`_missing_`** is a class method called when `Enum(value)` finds no member. Return
            a member to accept the value, or `None` to let the `ValueError` happen. A common use
            is forgiving lookups for user input.
            """
        ),
        code(
            """
            class Region(StrEnum):
                NORTH = auto()
                SOUTH = auto()

                @classmethod
                def _missing_(cls, value: object) -> Region | None:
                    if isinstance(value, str):
                        cleaned = value.strip().lower()
                        for member in cls:
                            if member.value == cleaned:
                                return member
                    return None


            print(f"{Region('  SOUTH ')=}, {Region('north')=}")
            print(raised_message(lambda: Region("east")))
            """
        ),
    ]


def _pattern_cells() -> list[NotebookNode]:
    """2.6.5 Design patterns, Pythonic style."""
    return [
        md(
            """
            ### 2.6.5 Design patterns, Pythonic style

            The classic patterns (from *Design Patterns*, 1994, written for C++ and Smalltalk)
            solve real problems, but many of their class hierarchies exist because those
            languages lacked first-class functions, modules and duck typing. Each pattern below
            is shown **non-Pythonic first** (a direct Java-style translation), then
            **Pythonic**.

            | Pattern | Problem | Pythonic tool |
            | --- | --- | --- |
            | Strategy | swap an algorithm | pass a function |
            | Factory | create the right class from data | dict of classes, `classmethod` constructors |
            | Singleton | one shared instance | a module-level object |
            | Registry | look implementations up by name | a decorator that fills a dict |
            | Observer | notify listeners of changes | a list of callables |
            | Adapter | make an old interface fit a new one | a small wrapper class (or `__getattr__`) |
            | Builder | build an object with many options | keyword arguments with defaults, `replace` |
            | Dependency injection | give an object its collaborators | constructor parameters typed with a Protocol |
            | Repository | hide storage behind a collection-like API | a Protocol + an in-memory implementation |

            #### Strategy

            **Non-Pythonic:** an abstract strategy class and one subclass per algorithm, each
            with a single method.
            """
        ),
        code(
            """
            class ShippingCostStrategy(ABC):
                @abstractmethod
                def cost(self, weight_kg: float) -> Decimal: ...


            class FlatRate(ShippingCostStrategy):
                def cost(self, weight_kg: float) -> Decimal:
                    return Decimal("50")


            class PerKilo(ShippingCostStrategy):
                def cost(self, weight_kg: float) -> Decimal:
                    return Decimal("20") * Decimal(str(weight_kg))


            class CheckoutWithStrategy:
                def __init__(self, strategy: ShippingCostStrategy) -> None:
                    self.strategy = strategy

                def shipping(self, weight_kg: float) -> Decimal:
                    return self.strategy.cost(weight_kg)


            print(CheckoutWithStrategy(PerKilo()).shipping(2.5))
            """
        ),
        md(
            """
            **Pythonic:** a strategy with one method *is* a function. Pass the function; use a
            dict when the choice comes from data. (A class is still right when the strategy has
            configuration and several methods.)
            """
        ),
        code(
            """
            type ShippingRule = Callable[[float], Decimal]


            def flat_rate(weight_kg: float) -> Decimal:
                return Decimal("50")


            def per_kilo(weight_kg: float) -> Decimal:
                return Decimal("20") * Decimal(str(weight_kg))


            SHIPPING_RULES: dict[str, ShippingRule] = {"flat": flat_rate, "per_kg": per_kilo}


            def shipping_cost(weight_kg: float, rule: ShippingRule = flat_rate) -> Decimal:
                return rule(weight_kg)


            print(
                shipping_cost(2.5, per_kilo),
                shipping_cost(2.5, SHIPPING_RULES["flat"]),
                shipping_cost(1, lambda kg: Decimal(0)),
            )
            """
        ),
        md(
            """
            #### Factory

            **Non-Pythonic:** a factory class with a growing `if/elif` chain that must be edited
            for every new type.
            """
        ),
        code(
            """
            class EmailMessage:
                def __init__(self, to: str) -> None:
                    self.to = to


            class SmsMessage:
                def __init__(self, to: str) -> None:
                    self.to = to


            class MessageFactory:
                def create(self, kind: str, to: str) -> object:
                    if kind == "email":
                        return EmailMessage(to)
                    elif kind == "sms":
                        return SmsMessage(to)
                    else:
                        raise ValueError(f"unknown kind {kind!r}")


            print(type(MessageFactory().create("sms", "+91 98765 43210")).__name__)
            """
        ),
        md(
            """
            **Pythonic:** classes are objects, so a dict maps names to classes. For "build this
            class from another representation", use alternative constructors
            (`@classmethod`, Unit 2.1.5).
            """
        ),
        code(
            """
            MESSAGE_TYPES: dict[str, type] = {"email": EmailMessage, "sms": SmsMessage}


            def create_message(kind: str, to: str) -> object:
                try:
                    return MESSAGE_TYPES[kind](to)
                except KeyError:
                    raise ValueError(f"unknown kind {kind!r}") from None


            print(type(create_message("email", "asha@example.com")).__name__)
            print(raised_message(lambda: create_message("fax", "123")))
            print(f"{date.fromisoformat('2026-11-07')=}  (an alternative constructor is a factory)")
            """
        ),
        md(
            """
            #### Singleton

            **Non-Pythonic:** override `__new__` (or use a metaclass, Unit 2.5.7) so the class
            always returns the same object. Calls *look* like they create new objects, which
            misleads readers, and tests cannot get a fresh instance.
            """
        ),
        code(
            """
            class ConfigSingleton:
                _instance: ConfigSingleton | None = None

                def __new__(cls) -> ConfigSingleton:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                        cls._instance.settings = {"currency": "INR"}
                    return cls._instance


            print(f"{ConfigSingleton() is ConfigSingleton()=}")
            """
        ),
        md(
            """
            **Pythonic:** a module is imported once and cached in `sys.modules` (Unit 3.3), so
            an object created at module level **is** a singleton. Create one instance and import
            it. For a lazily built one, `functools.cache` on a getter function works.
            """
        ),
        code(
            '''
            @dataclass
            class AppSettings:
                currency: str = "INR"
                tax_rate_percent: Decimal = Decimal("18")


            settings = AppSettings()  # in settings.py; everyone does `from settings import settings`


            @functools.cache
            def get_settings() -> AppSettings:
                """Built on first call, then cached (FastAPI apps often use this shape)."""
                return AppSettings()


            print(f"{get_settings() is get_settings()=}")
            print(f"{AppSettings() is settings=}  (tests can still make their own)")
            '''
        ),
        md(
            """
            #### Registry

            **Non-Pythonic:** a central list maintained by hand. Adding an exporter means
            editing two places, and forgetting the second is a silent bug.
            """
        ),
        code(
            """
            def export_csv(rows: list[dict[str, object]]) -> str:
                return "\\n".join(",".join(map(str, row.values())) for row in rows)


            def export_json(rows: list[dict[str, object]]) -> str:
                return json.dumps(rows)


            MANUAL_EXPORTERS = {"csv": export_csv, "json": export_json}  # remember to update!
            print(MANUAL_EXPORTERS["csv"]([{"sku": "PEN-01", "qty": 3}]))
            """
        ),
        md(
            """
            **Pythonic:** a decorator registers the function where it is defined (Unit 1.12.6);
            for classes, `__init_subclass__` does the same (Lab 2.5, exercise 4).
            """
        ),
        code(
            """
            REPORT_EXPORTERS: dict[str, Callable[[list[dict[str, object]]], str]] = {}


            def exporter(format_name: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
                def register(func: Callable[..., str]) -> Callable[..., str]:
                    REPORT_EXPORTERS[format_name] = func
                    return func

                return register


            @exporter("tsv")
            def export_tsv(rows: list[dict[str, object]]) -> str:
                return "\\n".join("\\t".join(map(str, row.values())) for row in rows)


            print(f"{sorted(REPORT_EXPORTERS)=}, {REPORT_EXPORTERS['tsv']([{'sku': 'PEN-01', 'qty': 3}])!r}")
            """
        ),
        md(
            """
            #### Observer

            **Non-Pythonic:** an `Observer` interface with an `update()` method, and one class
            per listener.
            """
        ),
        code(
            """
            class PriceObserver(ABC):
                @abstractmethod
                def update(self, sku: str, new_price: Decimal) -> None: ...


            class PrintingObserver(PriceObserver):
                def update(self, sku: str, new_price: Decimal) -> None:
                    print(f"  observer: {sku} now {new_price}")


            class ObservablePriceList:
                def __init__(self) -> None:
                    self._observers: list[PriceObserver] = []

                def attach(self, observer: PriceObserver) -> None:
                    self._observers.append(observer)

                def set_price(self, sku: str, new_price: Decimal) -> None:
                    for observer in self._observers:
                        observer.update(sku, new_price)


            observable_prices = ObservablePriceList()
            observable_prices.attach(PrintingObserver())
            observable_prices.set_price("PEN-01", Decimal("12"))
            """
        ),
        md(
            """
            **Pythonic:** listeners are callables: functions, lambdas, bound methods, objects
            with `__call__`. Keep a list of them. (Lab 2.6 grows this into a typed event bus.)
            """
        ),
        code(
            """
            class PriceList:
                def __init__(self) -> None:
                    self.listeners: list[Callable[[str, Decimal], None]] = []
                    self.prices: dict[str, Decimal] = {}

                def set_price(self, sku: str, new_price: Decimal) -> None:
                    self.prices[sku] = new_price
                    for listener in self.listeners:
                        listener(sku, new_price)


            price_changes: list[str] = []
            price_list = PriceList()
            price_list.listeners.append(lambda sku, price: price_changes.append(f"{sku}={price}"))
            price_list.listeners.append(lambda sku, price: print(f"  listener: {sku} now {price}"))
            price_list.set_price("PEN-01", Decimal("12"))
            print(f"{price_changes=}")
            """
        ),
        md(
            """
            #### Adapter

            **Non-Pythonic:** a full adapter class re-declaring every method of the target
            interface, forwarding each one by hand, often through an extra abstract base.
            """
        ),
        code(
            '''
            class LegacySmsGateway:
                """An old client with a different method name and argument order."""

                def send_text(self, body: str, phone_number: str) -> str:
                    return f"legacy sent {body!r} to {phone_number}"

                def balance(self) -> int:
                    return 120


            class MessageSenderBase(ABC):
                @abstractmethod
                def send(self, recipient: str, text: str) -> str: ...

                @abstractmethod
                def balance(self) -> int: ...


            class VerboseSmsAdapter(MessageSenderBase):
                def __init__(self, gateway: LegacySmsGateway) -> None:
                    self.gateway = gateway

                def send(self, recipient: str, text: str) -> str:
                    return self.gateway.send_text(text, recipient)

                def balance(self) -> int:  # pure forwarding, repeated for every method
                    return self.gateway.balance()


            print(VerboseSmsAdapter(LegacySmsGateway()).send("+91 98765 43210", "Your order shipped"))
            '''
        ),
        md(
            """
            **Pythonic:** the target is a Protocol (Unit 2.3.3), so no base class is needed.
            Write only the method that differs and forward the rest with `__getattr__` (Unit
            2.5.2). For a single function, an adapter can be a lambda.
            """
        ),
        code(
            """
            class MessageSender(Protocol):
                def send(self, recipient: str, text: str) -> str: ...


            class SmsAdapter:
                def __init__(self, gateway: LegacySmsGateway) -> None:
                    self._gateway = gateway

                def send(self, recipient: str, text: str) -> str:
                    return self._gateway.send_text(text, recipient)

                def __getattr__(self, attribute_name: str) -> Any:
                    if attribute_name == "_gateway":
                        raise AttributeError(attribute_name)
                    return getattr(self._gateway, attribute_name)


            def notify(sender: MessageSender, recipient: str) -> str:
                return sender.send(recipient, "Your order shipped")


            sms_adapter = SmsAdapter(LegacySmsGateway())
            print(notify(sms_adapter, "+91 98765 43210"), f"| {sms_adapter.balance()=}")
            """
        ),
        md(
            """
            #### Builder

            **Non-Pythonic:** a builder with one chained setter per option, needed in Java
            because it has no keyword arguments or default values.
            """
        ),
        code(
            """
            class HttpRequestBuilder:
                def __init__(self, url: str) -> None:
                    self._url, self._method, self._headers, self._timeout = url, "GET", {}, 10.0

                def method(self, method: str) -> HttpRequestBuilder:
                    self._method = method
                    return self

                def header(self, name: str, value: str) -> HttpRequestBuilder:
                    self._headers[name] = value
                    return self

                def timeout(self, seconds: float) -> HttpRequestBuilder:
                    self._timeout = seconds
                    return self

                def build(self) -> tuple[str, str, dict[str, str], float]:
                    return (self._method, self._url, self._headers, self._timeout)


            print(
                HttpRequestBuilder("https://api.example.com/orders")
                .method("POST")
                .header("Accept", "application/json")
                .timeout(5)
                .build()
            )
            """
        ),
        md(
            """
            **Pythonic:** keyword arguments with defaults *are* the builder. A frozen dataclass
            adds validation and `replace()` for variations of a base request.
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class HttpRequest:
                url: str
                method: str = "GET"
                headers: dict[str, str] = field(default_factory=dict)
                timeout_seconds: float = 10.0


            create_order = HttpRequest(
                "https://api.example.com/orders",
                method="POST",
                headers={"Accept": "application/json"},
                timeout_seconds=5,
            )
            list_orders = replace(create_order, method="GET")
            print(create_order)
            print(list_orders.method, list_orders.headers)
            """
        ),
        md(
            """
            #### Dependency injection

            **Non-Pythonic:** the service creates its own collaborators. It is welded to a real
            mail server, so testing it sends real e-mail (or needs monkey-patching).
            """
        ),
        code(
            """
            class SmtpMailer:
                def send(self, to: str, subject: str) -> None:
                    print(f"  (would open an SMTP connection and mail {to})")


            class SignupServiceHardWired:
                def __init__(self) -> None:
                    self.mailer = SmtpMailer()  # hidden, fixed dependency

                def register(self, email: str) -> str:
                    self.mailer.send(email, "Welcome!")
                    return f"registered {email}"


            print(SignupServiceHardWired().register("asha@example.com"))
            """
        ),
        md(
            """
            **Pythonic:** take the collaborator as a constructor parameter typed with a
            Protocol. Production passes the real one; tests pass a fake that records calls. No
            framework required (FastAPI's `Depends`, Phase 6, automates the wiring).
            """
        ),
        code(
            """
            class Mailer(Protocol):
                def send(self, to: str, subject: str) -> None: ...


            class RecordingMailer:
                def __init__(self) -> None:
                    self.sent: list[tuple[str, str]] = []

                def send(self, to: str, subject: str) -> None:
                    self.sent.append((to, subject))


            class SignupService:
                def __init__(self, mailer: Mailer) -> None:
                    self.mailer = mailer

                def register(self, email: str) -> str:
                    self.mailer.send(email, "Welcome!")
                    return f"registered {email}"


            fake_mailer = RecordingMailer()
            print(SignupService(fake_mailer).register("asha@example.com"), f"| {fake_mailer.sent=}")
            """
        ),
        md(
            """
            #### Repository

            **Non-Pythonic:** storage details (SQL strings, connection handling) are mixed into
            business logic, so the logic cannot be tested or reused without a database.
            """
        ),
        code(
            """
            import sqlite3


            def deactivate_stale_coupons_inline(connection: sqlite3.Connection, today: str) -> int:
                rows = connection.execute("SELECT code FROM coupons WHERE expires < ?", (today,)).fetchall()
                for (coupon_code,) in rows:
                    connection.execute("UPDATE coupons SET active = 0 WHERE code = ?", (coupon_code,))
                return len(rows)


            coupon_db = sqlite3.connect(":memory:")
            coupon_db.execute("CREATE TABLE coupons (code TEXT, expires TEXT, active INTEGER)")
            coupon_db.executemany(
                "INSERT INTO coupons VALUES (?, ?, 1)", [("OLD10", "2026-01-01"), ("NEW20", "2027-01-01")]
            )
            print(f"{deactivate_stale_coupons_inline(coupon_db, '2026-11-07')=}")
            coupon_db.close()
            """
        ),
        md(
            """
            **Pythonic:** a `CouponRepository` Protocol describes a collection-like API; the
            business rule depends only on it. An in-memory implementation serves tests (and this
            notebook); a SQLite or PostgreSQL one serves production (Phase 6). The Phase 2
            Project builds an inventory repository the same way.
            """
        ),
        code(
            """
            @dataclass
            class StoredCoupon:
                code: str
                expires: date
                active: bool = True


            class CouponRepository(Protocol):
                def list_active(self) -> list[StoredCoupon]: ...
                def save(self, coupon: StoredCoupon) -> None: ...


            class InMemoryCouponRepository:
                def __init__(self, coupons: list[StoredCoupon]) -> None:
                    self._coupons = {coupon.code: coupon for coupon in coupons}

                def list_active(self) -> list[StoredCoupon]:
                    return [coupon for coupon in self._coupons.values() if coupon.active]

                def save(self, coupon: StoredCoupon) -> None:
                    self._coupons[coupon.code] = coupon


            def deactivate_stale_coupons(repository: CouponRepository, today: date) -> int:
                stale = [coupon for coupon in repository.list_active() if coupon.expires < today]
                for coupon in stale:
                    repository.save(replace(coupon, active=False))
                return len(stale)


            coupon_repository = InMemoryCouponRepository(
                [StoredCoupon("OLD10", date(2026, 1, 1)), StoredCoupon("NEW20", date(2027, 1, 1))]
            )
            print(f"{deactivate_stale_coupons(coupon_repository, date(2026, 11, 7))=}")
            print(f"{[coupon.code for coupon in coupon_repository.list_active()]=}")
            """
        ),
    ]


def _value_entity_cells() -> list[NotebookNode]:
    """2.6.6 Value objects vs entities."""
    return [
        md(
            """
            ### 2.6.6 Value objects vs entities

            Domain-driven design separates two kinds of objects:

            | | Value object | Entity |
            | --- | --- | --- |
            | Identity | defined by its **values**: two equal values are interchangeable | defined by an **id** that stays the same while its data changes |
            | Equality | compare all fields | compare the id only |
            | Mutability | immutable: "changing" it means making a new one | mutable over its lifecycle |
            | Hashable | yes | by id, if at all |
            | Examples | `Money`, `EmailAddress`, `Address`, `DateRange`, `GeoPoint` | `Customer`, `Order`, `Warehouse`, `BankAccount` |
            | Python tool | `@dataclass(frozen=True)` (or a class like Unit 2.4's `Money`) | a class (or dataclass with `eq=False` / `compare=False` fields) |

            **A value object**: `DateRange` is immutable, compares by value, works as a dict key,
            and its operations return new objects.
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class DateRange:
                start: date
                end: date

                def __post_init__(self) -> None:
                    if self.end < self.start:
                        raise ValueError("end must not be before start")

                def __contains__(self, day: date) -> bool:
                    return self.start <= day <= self.end

                def extended_by(self, days: int) -> DateRange:
                    return replace(self, end=date.fromordinal(self.end.toordinal() + days))


            sale_period = DateRange(date(2026, 11, 1), date(2026, 11, 10))
            longer_sale = sale_period.extended_by(5)
            print(f"{sale_period == DateRange(date(2026, 11, 1), date(2026, 11, 10))=}")
            print(f"{date(2026, 11, 12) in sale_period=}, {date(2026, 11, 12) in longer_sale=}")
            print(f"{ {sale_period: 'Diwali sale'}[DateRange(date(2026, 11, 1), date(2026, 11, 10))]=}")
            """
        ),
        md(
            """
            **An entity**: a `CustomerAccount` keeps its identity while its e-mail and status
            change. Equality and hashing use only `account_id`, so the same customer loaded twice
            (with different data) is still "the same customer". Here `compare=False` on every
            other field plus `unsafe_hash=True` makes the hash use only the id, which never
            changes.
            """
        ),
        code(
            """
            @dataclass(unsafe_hash=True)
            class CustomerAccount:
                account_id: int
                email: EmailAddress = field(compare=False)
                active: bool = field(default=True, compare=False)

                def change_email(self, new_email: str) -> None:
                    self.email = EmailAddress(new_email)  # replace the value object


            loaded_yesterday = CustomerAccount(7, EmailAddress("asha@old.in"))
            loaded_today = CustomerAccount(7, EmailAddress("asha@new.in"), active=False)
            other_customer = CustomerAccount(8, EmailAddress("asha@old.in"))
            print(f"{loaded_yesterday == loaded_today=}  (same id)")
            print(f"{loaded_yesterday == other_customer=}  (same data, different id)")
            loaded_yesterday.change_email("ASHA@new.in")
            print(f"{loaded_yesterday.email=}, {len({loaded_yesterday, loaded_today})=}")
            """
        ),
        md(
            """
            > **Note:** entities usually **contain** value objects (`CustomerAccount.email`,
            > `Order.total: Money`). Change an entity by replacing its value objects, never by
            > mutating them, and the bugs from shared mutable state (Unit 1.2) disappear.
            """
        ),
        *predict_cells(
            """
            from enum import Enum

            class Colour(Enum):
                RED = 1
                CRIMSON = 1
                BLUE = 2

            print(Colour.CRIMSON is Colour.RED)
            print(Colour.CRIMSON)
            print(len(Colour), [colour.name for colour in Colour])
            """,
            """
            ```text
            True
            Colour.RED
            2 ['RED', 'BLUE']
            ```

            `CRIMSON = 1` reuses `RED`'s value, so it becomes an **alias**: the same object as
            `Colour.RED`, printed with the canonical name. Iteration and `len()` skip aliases
            (they appear only in `__members__`). Add `@unique` if duplicate values are a
            mistake.
            """,
            """
            class Colour(Enum):
                RED = 1
                CRIMSON = 1
                BLUE = 2


            print(Colour.CRIMSON is Colour.RED)
            print(Colour.CRIMSON)
            print(len(Colour), [colour.name for colour in Colour])
            """,
        ),
    ]


def _lab_dataclass_enum_cells() -> list[NotebookNode]:
    """Lab 2.6 exercises 1–2."""
    return [
        md(
            """
            ### Lab 2.6

            Four exercises. For each, complete the stub, then run the check cell. Until then the
            checks print FAIL; that is expected. In exercise 2 one check ("is a str") already
            passes on the stub because the base class is given; keep it passing.

            #### Exercise 1 — `Address` / `Customer` dataclasses with validation

            Replace the stubs with dataclasses (2.6.1). Earlier labs used these class names for
            other shapes; these definitions replace them.

            - `Address(street, city, pin_code)` is a **frozen** dataclass. `__post_init__`
              strips `street` and `city`; if either is then empty, raise
              `ValueError("street and city are required")`. `pin_code` must be six digits not
              starting with `0`, otherwise `ValueError(f"invalid PIN code: {pin_code!r}")`.
            - `Customer(customer_id, name, email, addresses=[])` is a dataclass (an entity,
              2.6.6). `name` is stripped and must not be empty
              (`ValueError("name is required")`); `email` is stripped and lower-cased and must
              contain exactly one `@` with a `.` after it, otherwise
              `ValueError(f"invalid email: {email!r}")` (showing the original input).
              `addresses` defaults to a **new** list per customer.
            - Two customers are equal when their `customer_id`s are equal, whatever the other
              fields say.
            - `customer.add_address(address)` appends the address and returns `True`, or returns
              `False` if an equal address is already there.
            """
        ),
        code(
            """
            class Address:
                def __init__(self, street: str, city: str, pin_code: str) -> None:
                    raise NotImplementedError("Lab 2.6: implement Address as a frozen dataclass")


            class Customer:
                def __init__(
                    self, customer_id: int, name: str, email: str, addresses: list[Address] | None = None
                ) -> None:
                    raise NotImplementedError("Lab 2.6: implement Customer as a dataclass")
            """
        ),
        md("Run the checks."),
        code(
            """
            def address_errors() -> list[str]:
                return [
                    raised_message(lambda: Address("  ", "Pune", "411001")),
                    raised_message(lambda: Address("MG Road", "Pune", "011001")),
                    raised_message(lambda: Address("MG Road", "Pune", "41100")),
                ]


            def address_book() -> tuple[bool, bool, int]:
                customer = Customer(1, "Asha", "asha@example.com")
                first = customer.add_address(Address("MG Road", "Pune", "411001"))
                again = customer.add_address(Address(" MG Road ", "Pune", "411001"))
                return first, again, len(customer.addresses)


            run_checks(
                [
                    (
                        "is a dataclass",
                        lambda: (dataclasses.is_dataclass(Address), dataclasses.is_dataclass(Customer)),
                        (True, True),
                    ),
                    (
                        "address stripped",
                        lambda: (
                            Address("  MG Road ", " Pune ", "411001").street,
                            Address("  MG Road ", " Pune ", "411001").city,
                        ),
                        ("MG Road", "Pune"),
                    ),
                    (
                        "address errors",
                        address_errors,
                        [
                            "ValueError: street and city are required",
                            "ValueError: invalid PIN code: '011001'",
                            "ValueError: invalid PIN code: '41100'",
                        ],
                    ),
                    (
                        "address frozen",
                        lambda: raised_error_name(
                            lambda: set_attribute(Address("MG Road", "Pune", "411001"), "city", "Mumbai")
                        ),
                        "FrozenInstanceError",
                    ),
                    (
                        "address hashable",
                        lambda: len(
                            {Address("MG Road", "Pune", "411001"), Address("MG Road ", "Pune", "411001")}
                        ),
                        1,
                    ),
                    (
                        "replace validates",
                        lambda: raised_message(
                            lambda: replace(Address("MG Road", "Pune", "411001"), pin_code="0")
                        ),
                        "ValueError: invalid PIN code: '0'",
                    ),
                    (
                        "email normalized",
                        lambda: Customer(1, " Asha ", "  Asha@Example.COM ").email,
                        "asha@example.com",
                    ),
                    ("name stripped", lambda: Customer(1, " Asha ", "asha@example.com").name, "Asha"),
                    (
                        "bad email",
                        lambda: raised_message(lambda: Customer(1, "Asha", " asha@example ")),
                        "ValueError: invalid email: ' asha@example '",
                    ),
                    (
                        "empty name",
                        lambda: raised_message(lambda: Customer(1, "  ", "a@b.in")),
                        "ValueError: name is required",
                    ),
                    (
                        "equal by id",
                        lambda: (
                            Customer(1, "Asha", "asha@example.com") == Customer(1, "A. Rao", "rao@example.com")
                        ),
                        True,
                    ),
                    (
                        "different id",
                        lambda: (
                            Customer(1, "Asha", "asha@example.com") == Customer(2, "Asha", "asha@example.com")
                        ),
                        False,
                    ),
                    (
                        "separate lists",
                        lambda: (
                            Customer(1, "A", "a@b.in").addresses is not Customer(2, "B", "b@b.in").addresses
                        ),
                        True,
                    ),
                    ("add_address", address_book, (True, False, 1)),
                    (
                        "asdict nests",
                        lambda: asdict(
                            Customer(1, "Asha", "asha@example.com", [Address("MG Road", "Pune", "411001")])
                        )["addresses"],
                        [{"street": "MG Road", "city": "Pune", "pin_code": "411001"}],
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — `OrderStatus(StrEnum)` with allowed transitions

            - Members `PENDING`, `PAID`, `SHIPPED`, `DELIVERED`, `CANCELLED` whose values are the
              lower-case names (use `auto()`).
            - Allowed moves: pending → paid or cancelled; paid → shipped or cancelled; shipped
              → delivered. Delivered and cancelled are final.
            - `status.can_transition_to(target)` → `bool`; `status.transition_to(target)`
              returns `target` or raises `ValueError(f"cannot go from {status} to {target}")`
              (e.g. `"cannot go from shipped to pending"`).
            - `status.is_final` property.
            - `_missing_` accepts any capitalization and surrounding spaces
              (`OrderStatus(" PAID ")`); anything else still raises `ValueError`.
            """
        ),
        code(
            '''
            class OrderStatus(StrEnum):
                """Add the members, the transition rules, is_final and _missing_."""

                def can_transition_to(self, target: OrderStatus) -> bool:
                    raise NotImplementedError("Lab 2.6: implement OrderStatus.can_transition_to")

                def transition_to(self, target: OrderStatus) -> OrderStatus:
                    raise NotImplementedError("Lab 2.6: implement OrderStatus.transition_to")
            '''
        ),
        md("Run the checks."),
        code(
            """
            def happy_path() -> list[str]:
                status = OrderStatus.PENDING
                visited = [str(status)]
                for target in (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
                    status = status.transition_to(target)
                    visited.append(str(status))
                return visited


            run_checks(
                [
                    (
                        "values",
                        lambda: [status.value for status in OrderStatus],
                        ["pending", "paid", "shipped", "delivered", "cancelled"],
                    ),
                    ("is a str", lambda: issubclass(OrderStatus, str), True),
                    ("equals its value", lambda: OrderStatus.PAID == "paid", True),
                    ("json", lambda: json.dumps({"status": OrderStatus.SHIPPED}), '{"status": "shipped"}'),
                    ("happy path", happy_path, ["pending", "paid", "shipped", "delivered"]),
                    (
                        "allowed",
                        lambda: (
                            OrderStatus.PENDING.can_transition_to(OrderStatus.CANCELLED),
                            OrderStatus.PAID.can_transition_to(OrderStatus.CANCELLED),
                        ),
                        (True, True),
                    ),
                    (
                        "not allowed",
                        lambda: (
                            OrderStatus.SHIPPED.can_transition_to(OrderStatus.CANCELLED),
                            OrderStatus.PENDING.can_transition_to(OrderStatus.SHIPPED),
                        ),
                        (False, False),
                    ),
                    (
                        "error",
                        lambda: raised_message(lambda: OrderStatus.SHIPPED.transition_to(OrderStatus.PENDING)),
                        "ValueError: cannot go from shipped to pending",
                    ),
                    (
                        "final states",
                        lambda: [status.value for status in OrderStatus if status.is_final],
                        ["delivered", "cancelled"],
                    ),
                    ("_missing_", lambda: OrderStatus(" PAID ") is OrderStatus.PAID, True),
                    ("unknown", lambda: raised_error_name(lambda: OrderStatus("lost")), "ValueError"),
                ]
            )
            """
        ),
    ]


def _lab_flag_bus_cells() -> list[NotebookNode]:
    """Lab 2.6 exercises 3–4."""
    return [
        md(
            """
            #### Exercise 3 — `Permission(Flag)`

            - Single-bit members `READ`, `WRITE`, `DELETE`, `SHARE` (`auto()`), plus combined
              aliases `VIEWER = READ`, `EDITOR = READ | WRITE`,
              `OWNER = READ | WRITE | DELETE | SHARE`.
            - `has_permission(granted, required)` → `True` only if **every** bit of `required`
              is in `granted`.
            - `parse_permissions(text)` turns `"read, Write"` into `Permission.READ |
              Permission.WRITE` (comma-separated, any case and spacing; `""` gives
              `Permission(0)`); an unknown name raises
              `ValueError(f"unknown permission: {name!r}")` with the cleaned name.
            - `permission_names(permission)` → the single-bit member names in definition order,
              e.g. `["READ", "WRITE"]` for `EDITOR`.
            """
        ),
        code(
            '''
            class Permission(Flag):
                """Add the members and aliases."""


            def has_permission(granted: Permission, required: Permission) -> bool:
                raise NotImplementedError("Lab 2.6: implement has_permission")


            def parse_permissions(text: str) -> Permission:
                raise NotImplementedError("Lab 2.6: implement parse_permissions")


            def permission_names(permission: Permission) -> list[str]:
                raise NotImplementedError("Lab 2.6: implement permission_names")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("single bits", lambda: [member.value for member in Permission], [1, 2, 4, 8]),
                    (
                        "aliases",
                        lambda: (
                            Permission.EDITOR == Permission.READ | Permission.WRITE,
                            Permission.VIEWER is Permission.READ,
                        ),
                        (True, True),
                    ),
                    (
                        "in",
                        lambda: (Permission.WRITE in Permission.EDITOR, Permission.DELETE in Permission.EDITOR),
                        (True, False),
                    ),
                    (
                        "has_permission",
                        lambda: (
                            has_permission(Permission.OWNER, Permission.EDITOR),
                            has_permission(Permission.EDITOR, Permission.READ | Permission.DELETE),
                        ),
                        (True, False),
                    ),
                    ("parse", lambda: parse_permissions("read, Write") == Permission.EDITOR, True),
                    ("parse spacing", lambda: parse_permissions("  SHARE,delete ").value, 12),
                    ("parse empty", lambda: parse_permissions("").value, 0),
                    (
                        "parse unknown",
                        lambda: raised_message(lambda: parse_permissions("read, Fly")),
                        "ValueError: unknown permission: 'fly'",
                    ),
                    ("names", lambda: permission_names(Permission.EDITOR), ["READ", "WRITE"]),
                    (
                        "names after removing",
                        lambda: permission_names(Permission.OWNER & ~Permission.READ),
                        ["WRITE", "DELETE", "SHARE"],
                    ),
                    ("names of nothing", lambda: permission_names(Permission(0)), []),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 4 — an `EventBus`

            A publish/subscribe hub that dispatches on the **event class**:

            - `subscribe(event_type, handler)` registers a handler and returns a function that
              unsubscribes it. `on(event_type)` is the decorator form (returns the handler).
            - `publish(event)` calls the handlers for `type(event)` **and its base classes**
              (most specific class first, following the MRO; within a class, in subscription
              order) and returns how many handlers ran. A handler that raises must not stop the
              others: collect the exceptions and, after all handlers ran, raise
              `ExceptionGroup("event handlers failed", errors)` (Unit 1.14.6).
            - `subscriber_count(event_type)` → number of handlers registered for exactly that
              class.
            """
        ),
        code(
            '''
            class EventBus:
                """Dispatch events to handlers subscribed to their class or a base class."""

                def __init__(self) -> None:
                    raise NotImplementedError("Lab 2.6: implement EventBus")
            '''
        ),
        md(
            "Run the checks. The events are frozen dataclasses; `OrderPlaced` and `OrderShipped` extend `Event`."
        ),
        code(
            """
            @dataclass(frozen=True)
            class Event:
                order_id: str


            @dataclass(frozen=True)
            class OrderPlaced(Event):
                amount_paise: int


            @dataclass(frozen=True)
            class OrderShipped(Event):
                courier: str


            def dispatch_log() -> tuple[int, int, list[str]]:
                bus, log = EventBus(), []
                bus.subscribe(Event, lambda event: log.append(f"audit {event.order_id}"))
                bus.subscribe(OrderPlaced, lambda event: log.append(f"invoice {event.amount_paise}"))
                bus.subscribe(OrderPlaced, lambda event: log.append("thank-you mail"))
                placed_count = bus.publish(OrderPlaced("ORD-1", 49_900))
                shipped_count = bus.publish(OrderShipped("ORD-1", "BlueDart"))
                return placed_count, shipped_count, log


            def unsubscribe_flow() -> tuple[int, int, int]:
                bus, seen = EventBus(), []
                stop = bus.subscribe(OrderShipped, seen.append)
                first = bus.publish(OrderShipped("ORD-2", "DTDC"))
                stop()
                return first, bus.publish(OrderShipped("ORD-3", "DTDC")), len(seen)


            def decorator_form() -> tuple[int, str]:
                bus = EventBus()

                @bus.on(OrderPlaced)
                def record(event: Event) -> None:
                    pass

                return bus.subscriber_count(OrderPlaced), record.__name__


            def failing_handlers() -> tuple[str, int, list[str], list[str]]:
                bus, log = EventBus(), []
                bus.subscribe(Event, lambda event: 1 / 0)
                bus.subscribe(Event, lambda event: log.append("still runs"))
                bus.subscribe(Event, lambda event: {}["missing"])
                try:
                    bus.publish(Event("ORD-4"))
                except ExceptionGroup as group:
                    return (
                        group.message,
                        len(group.exceptions),
                        sorted(type(error).__name__ for error in group.exceptions),
                        log,
                    )
                return "no group", 0, [], log


            run_checks(
                [
                    (
                        "dispatch by MRO",
                        dispatch_log,
                        (3, 1, ["invoice 49900", "thank-you mail", "audit ORD-1", "audit ORD-1"]),
                    ),
                    ("unsubscribe", unsubscribe_flow, (1, 0, 1)),
                    ("no subscribers", lambda: EventBus().publish(Event("ORD-5")), 0),
                    ("decorator form", decorator_form, (1, "record")),
                    ("subscriber_count is exact", lambda: EventBus().subscriber_count(Event), 0),
                    (
                        "errors grouped",
                        failing_handlers,
                        ("event handlers failed", 2, ["KeyError", "ZeroDivisionError"], ["still runs"]),
                    ),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.6."""
    return [
        md(
            """
            ### Recap — Unit 2.6

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | `@dataclass` | Declare typed fields; get `__init__`, `__repr__`, `__eq__`, `__match_args__` | class fields + constructor |
            | `field()` | `default_factory` for mutable defaults; `repr`, `compare`, `init`, `kw_only`, `metadata`, `doc` | — |
            | `frozen` / `order` / `slots` / `kw_only` | Immutable + hashable / tuple ordering / no `__dict__` / keyword-only | `Object.freeze` |
            | `__post_init__` / `InitVar` | Validate and normalize; init-only inputs | constructor body |
            | `asdict` / `replace` / `fields` | Recursive dict copy / copy with changes (re-validated) / introspection | `{...obj, x: 1}` |
            | Record types | dataclass inside, NamedTuple for tuples, TypedDict for JSON, Pydantic at the edges | TS types vs classes |
            | `TypedDict` | Type-checker-only description of a dict; `Required`, `NotRequired`, `ReadOnly` | TS object types |
            | `Enum` | Fixed set of singletons; lookup by value `E(v)` and name `E[n]` | TS `enum` |
            | `IntEnum` / `StrEnum` | Members are ints / strs (JSON-friendly) | string enums |
            | `Flag` / `IntFlag` | Combinable bits with names, `in`, iteration | bit masks |
            | `@unique`, `_missing_` | Forbid aliases; customize failed lookups | — |
            | Patterns | Functions, dicts, modules, decorators and Protocols replace most hierarchies | same |
            | Value object vs entity | Equal by value and immutable vs equal by id with a lifecycle | — |

            **Further reading**

            - [`dataclasses`](https://docs.python.org/3/library/dataclasses.html),
              [`copy.replace`](https://docs.python.org/3/library/copy.html#copy.replace)
            - [`enum`](https://docs.python.org/3/library/enum.html) and the
              [Enum HOWTO](https://docs.python.org/3/howto/enum.html)
            - [`typing.TypedDict`](https://docs.python.org/3/library/typing.html#typing.TypedDict),
              [`typing.NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple)
            - [PEP 557 — Data Classes](https://peps.python.org/pep-0557/),
              [PEP 435 — Enums](https://peps.python.org/pep-0435/),
              [PEP 589 — TypedDict](https://peps.python.org/pep-0589/),
              [PEP 655 — Required / NotRequired](https://peps.python.org/pep-0655/),
              [PEP 705 — ReadOnly](https://peps.python.org/pep-0705/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.6 and Lab 2.6."""
    return [
        *_overview_cells(),
        *_dataclass_basics_cells(),
        *_dataclass_options_cells(),
        *_record_comparison_cells(),
        *_typeddict_cells(),
        *_enum_cells(),
        *_pattern_cells(),
        *_value_entity_cells(),
        *_lab_dataclass_enum_cells(),
        *_lab_flag_bus_cells(),
        *_recap_cells(),
    ]
