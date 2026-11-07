"""Reference solutions for Phase 2 labs.

Run from the repository root:

    uv run python exercises/solutions/phase2_solutions.py
"""

import dataclasses
import functools
import inspect
import io
import json
import math
import sqlite3
import time
import typing
from abc import ABC, abstractmethod
from collections import UserDict, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Flag, StrEnum, auto
from math import pi
from typing import Any, NamedTuple, Protocol, Self, runtime_checkable

type TestCase = tuple[str, Callable[[], object], object]

PAISE = Decimal("0.01")


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the script
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


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


# Lab 2.1 -------------------------------------------------------------------------------------


class Transaction(NamedTuple):
    """One entry in a BankAccount history."""

    kind: str  # "open", "deposit" or "withdrawal"
    amount: Decimal
    balance_after: Decimal


def _require_decimal(amount: object, label: str) -> Decimal:
    """Return amount if it is a Decimal, else raise TypeError naming the label."""
    if not isinstance(amount, Decimal):
        raise TypeError(f"{label} must be a Decimal, got {type(amount).__name__}")
    return amount


class BankAccount:
    """A bank account with a read-only, validated balance and an append-only history."""

    def __init__(self, owner: str, opening_balance: Decimal = Decimal("0")) -> None:
        _require_decimal(opening_balance, "opening_balance")
        if opening_balance < 0:
            raise ValueError("opening balance cannot be negative")
        self.owner = owner
        self._balance = opening_balance
        self._history = [Transaction("open", opening_balance, opening_balance)]

    @property
    def balance(self) -> Decimal:
        """Current balance (read-only: change it through deposit / withdraw)."""
        return self._balance

    @property
    def history(self) -> tuple[Transaction, ...]:
        """Every transaction so far, oldest first, as an immutable tuple."""
        return tuple(self._history)

    @staticmethod
    def _validated_amount(amount: object) -> Decimal:
        """Check that a deposit or withdrawal amount is a positive Decimal."""
        checked_amount = _require_decimal(amount, "amount")
        if checked_amount <= 0:
            raise ValueError("amount must be positive")
        return checked_amount

    def deposit(self, amount: Decimal) -> Decimal:
        """Add amount to the balance and return the new balance."""
        checked_amount = self._validated_amount(amount)
        self._balance += checked_amount
        self._history.append(Transaction("deposit", checked_amount, self._balance))
        return self._balance

    def withdraw(self, amount: Decimal) -> Decimal:
        """Take amount from the balance and return the new balance."""
        checked_amount = self._validated_amount(amount)
        if checked_amount > self._balance:
            raise ValueError(
                f"insufficient funds: balance {self._balance:.2f}, requested {checked_amount:.2f}"
            )
        self._balance -= checked_amount
        self._history.append(Transaction("withdrawal", checked_amount, self._balance))
        return self._balance


ABSOLUTE_ZERO_CELSIUS = -273.15


class Temperature:
    """A temperature stored in Celsius, readable and writable in Fahrenheit."""

    def __init__(self, celsius: float) -> None:
        self.celsius = celsius  # goes through the validating setter

    @property
    def celsius(self) -> float:
        """Degrees Celsius."""
        return self._celsius

    @celsius.setter
    def celsius(self, value: float) -> None:
        if value < ABSOLUTE_ZERO_CELSIUS:
            raise ValueError(f"below absolute zero: {value} °C")
        self._celsius = value

    @property
    def fahrenheit(self) -> float:
        """Degrees Fahrenheit, computed from Celsius."""
        return self._celsius * 9 / 5 + 32

    @fahrenheit.setter
    def fahrenheit(self, value: float) -> None:
        self.celsius = (value - 32) * 5 / 9

    @property
    def kelvin(self) -> float:
        """Kelvin (read-only)."""
        return self._celsius - ABSOLUTE_ZERO_CELSIUS


class User:
    """A site user; from_dict builds an instance of whichever class it is called on."""

    role = "member"

    def __init__(self, username: str, email: str, is_active: bool = True) -> None:
        self.username = username
        self.email = email
        self.is_active = is_active

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a user from a mapping (username and email required, is_active optional)."""
        for field_name in ("username", "email"):
            if field_name not in data:
                raise ValueError(f"missing field: {field_name}")
        return cls(
            username=data["username"].strip(),
            email=data["email"].strip().lower(),
            is_active=data.get("is_active", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict, including the class-level role."""
        return {
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "role": self.role,
        }


class AdminUser(User):
    """A user with the admin role."""

    role = "admin"


class CartItem:
    """One line of a shopping cart."""

    def __init__(self, sku: str, unit_price: Decimal, quantity: int = 1) -> None:
        _require_decimal(unit_price, "unit_price")
        if unit_price < 0:
            raise ValueError("unit price cannot be negative")
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        self.sku = sku
        self.unit_price = unit_price
        self.quantity = quantity

    @property
    def line_total(self) -> Decimal:
        """unit_price × quantity."""
        return self.unit_price * self.quantity


class ShoppingCart:
    """A cart of CartItems keyed by SKU, with exact Decimal totals."""

    def __init__(self) -> None:
        self._items: dict[str, CartItem] = {}

    def add(self, sku: str, unit_price: Decimal, quantity: int = 1) -> CartItem:
        """Add quantity of sku; an existing line grows if the unit price matches."""
        existing_item = self._items.get(sku)
        if existing_item is None:
            new_item = CartItem(sku, unit_price, quantity)
            self._items[sku] = new_item
            return new_item
        if existing_item.unit_price != unit_price:
            raise ValueError(f"price mismatch for {sku}")
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        existing_item.quantity += quantity
        return existing_item

    def remove(self, sku: str, quantity: int | None = None) -> None:
        """Remove quantity of sku (all of it when quantity is None)."""
        if sku not in self._items:
            raise KeyError(sku)
        item = self._items[sku]
        if quantity is None or quantity >= item.quantity:
            del self._items[sku]
        else:
            item.quantity -= quantity

    @property
    def items(self) -> tuple[CartItem, ...]:
        """The cart lines in the order they were first added."""
        return tuple(self._items.values())

    @property
    def item_count(self) -> int:
        """Total quantity across every line."""
        return sum(item.quantity for item in self._items.values())

    @property
    def subtotal(self) -> Decimal:
        """Sum of line totals before tax."""
        return sum((item.line_total for item in self._items.values()), Decimal("0"))

    def total(self, tax_rate_percent: Decimal = Decimal("18")) -> Decimal:
        """Subtotal plus tax, rounded half-up to the paisa."""
        taxed_amount = self.subtotal * (1 + tax_rate_percent / 100)
        return taxed_amount.quantize(PAISE, rounding=ROUND_HALF_UP)


def check_lab_2_1() -> None:
    """Run the same checks as the Lab 2.1 check cells in the notebook."""
    print("Exercise 1 — BankAccount")

    def sample_account() -> BankAccount:
        """An account opened with 100.00, then +50.00 and -30.00."""
        account = BankAccount("Asha", Decimal("100.00"))
        account.deposit(Decimal("50.00"))
        account.withdraw(Decimal("30.00"))
        return account

    def balance_after_failed_withdrawal() -> tuple[Decimal, int]:
        """Balance and history length after an overdraft attempt."""
        account = sample_account()
        raised_error_name(lambda: account.withdraw(Decimal("500.00")))
        return account.balance, len(account.history)

    def assign_balance() -> None:
        """Try to overwrite the read-only balance."""
        account = sample_account()
        account.balance = Decimal("1000000")  # type: ignore[misc]

    def history_is_a_copy() -> bool:
        """True if the returned history cannot change the account."""
        account = sample_account()
        history = account.history
        return type(history) is tuple and len(account.history) == 3

    run_checks(
        [
            ("balance", lambda: sample_account().balance, Decimal("120.00")),
            (
                "history",
                lambda: sample_account().history,
                (
                    Transaction("open", Decimal("100.00"), Decimal("100.00")),
                    Transaction("deposit", Decimal("50.00"), Decimal("150.00")),
                    Transaction("withdrawal", Decimal("30.00"), Decimal("120.00")),
                ),
            ),
            ("history is a tuple", history_is_a_copy, True),
            ("balance is read-only", lambda: raised_error_name(assign_balance), "AttributeError"),
            ("default opening", lambda: BankAccount("Ravi").balance, Decimal("0")),
            (
                "returns new balance",
                lambda: BankAccount("Ravi").deposit(Decimal("10.50")),
                Decimal("10.50"),
            ),
            (
                "non-positive amount",
                lambda: raised_message(lambda: BankAccount("Ravi").deposit(Decimal("0"))),
                "ValueError: amount must be positive",
            ),
            (
                "float amount",
                lambda: raised_message(lambda: BankAccount("Ravi").deposit(10.5)),  # type: ignore[arg-type]
                "TypeError: amount must be a Decimal, got float",
            ),
            (
                "overdraft",
                lambda: raised_message(lambda: sample_account().withdraw(Decimal("500"))),
                "ValueError: insufficient funds: balance 120.00, requested 500.00",
            ),
            (
                "failed withdrawal changes nothing",
                balance_after_failed_withdrawal,
                (Decimal("120.00"), 3),
            ),
            (
                "negative opening",
                lambda: raised_message(lambda: BankAccount("Ravi", Decimal("-1"))),
                "ValueError: opening balance cannot be negative",
            ),
        ]
    )

    print("Exercise 2 — Temperature")

    def set_fahrenheit(value: float) -> float:
        """Set Fahrenheit on a 20 °C temperature and return the Celsius value."""
        temperature = Temperature(20)
        temperature.fahrenheit = value
        return round(temperature.celsius, 2)

    def rejected_fahrenheit_keeps_value() -> float:
        """Celsius after an invalid Fahrenheit assignment."""
        temperature = Temperature(20)
        raised_error_name(lambda: setattr(temperature, "fahrenheit", -500))
        return temperature.celsius

    run_checks(
        [
            ("100 °C in °F", lambda: round(Temperature(100).fahrenheit, 2), 212.0),
            ("-40 is -40", lambda: round(Temperature(-40).fahrenheit, 2), -40.0),
            ("set °F", lambda: set_fahrenheit(212), 100.0),
            ("set °F to 32", lambda: set_fahrenheit(32), 0.0),
            ("kelvin", lambda: round(Temperature(25).kelvin, 2), 298.15),
            (
                "kelvin is read-only",
                lambda: raised_error_name(lambda: setattr(Temperature(25), "kelvin", 0)),
                "AttributeError",
            ),
            (
                "below absolute zero",
                lambda: raised_message(lambda: Temperature(-300)),
                "ValueError: below absolute zero: -300 °C",
            ),
            (
                "°F setter validates",
                lambda: raised_error_name(lambda: setattr(Temperature(0), "fahrenheit", -500)),
                "ValueError",
            ),
            ("rejected value leaves state", rejected_fahrenheit_keeps_value, 20),
            (
                "fahrenheit is a property",
                lambda: type(Temperature.__dict__["fahrenheit"]).__name__,
                "property",
            ),
        ]
    )

    print("Exercise 3 — User.from_dict")

    class GuestUser(User):
        """A third subclass the stub has never seen."""

        role = "guest"

    raw_user = {"username": "  meena ", "email": " Meena@Example.COM ", "plan": "pro"}
    run_checks(
        [
            ("returns User", lambda: type(User.from_dict(raw_user)).__name__, "User"),
            ("subclass-aware", lambda: type(AdminUser.from_dict(raw_user)).__name__, "AdminUser"),
            ("unseen subclass", lambda: type(GuestUser.from_dict(raw_user)).__name__, "GuestUser"),
            (
                "fields cleaned",
                lambda: User.from_dict(raw_user).to_dict(),
                {
                    "username": "meena",
                    "email": "meena@example.com",
                    "is_active": True,
                    "role": "member",
                },
            ),
            ("admin role", lambda: AdminUser.from_dict(raw_user).to_dict()["role"], "admin"),
            (
                "is_active read",
                lambda: User.from_dict({**raw_user, "is_active": False}).is_active,
                False,
            ),
            (
                "round trip",
                lambda: AdminUser.from_dict(AdminUser.from_dict(raw_user).to_dict()).to_dict(),
                {
                    "username": "meena",
                    "email": "meena@example.com",
                    "is_active": True,
                    "role": "admin",
                },
            ),
            (
                "missing email",
                lambda: raised_message(lambda: User.from_dict({"username": "x"})),
                "ValueError: missing field: email",
            ),
            (
                "missing both",
                lambda: raised_message(lambda: User.from_dict({})),
                "ValueError: missing field: username",
            ),
            (
                "input untouched",
                lambda: (User.from_dict(raw_user), raw_user["username"])[1],
                "  meena ",
            ),
            ("is a classmethod", lambda: type(User.__dict__["from_dict"]).__name__, "classmethod"),
        ]
    )

    print("Exercise 4 — ShoppingCart and CartItem")

    def sample_cart() -> ShoppingCart:
        """Two lines: 2 × 499.00 soap (added in two calls) and 1 × 1250.50 rice."""
        cart = ShoppingCart()
        cart.add("SOAP", Decimal("499.00"))
        cart.add("RICE-5KG", Decimal("1250.50"))
        cart.add("SOAP", Decimal("499.00"))
        return cart

    def lines(cart: ShoppingCart) -> list[tuple[str, int, Decimal]]:
        """(sku, quantity, line_total) for each cart line."""
        return [(item.sku, item.quantity, item.line_total) for item in cart.items]

    def after_remove(sku: str, quantity: int | None) -> list[tuple[str, int, Decimal]]:
        """Lines of the sample cart after one remove call."""
        cart = sample_cart()
        cart.remove(sku, quantity)
        return lines(cart)

    run_checks(
        [
            (
                "lines merge",
                lambda: lines(sample_cart()),
                [("SOAP", 2, Decimal("998.00")), ("RICE-5KG", 1, Decimal("1250.50"))],
            ),
            ("item_count", lambda: sample_cart().item_count, 3),
            ("subtotal", lambda: sample_cart().subtotal, Decimal("2248.50")),
            ("total with 18% GST", lambda: sample_cart().total(), Decimal("2653.23")),
            ("total with 5% GST", lambda: sample_cart().total(Decimal("5")), Decimal("2360.93")),
            (
                "empty cart",
                lambda: (ShoppingCart().subtotal, ShoppingCart().total()),
                (Decimal("0"), Decimal("0.00")),
            ),
            ("items is a tuple", lambda: type(sample_cart().items).__name__, "tuple"),
            (
                "price mismatch",
                lambda: raised_message(lambda: sample_cart().add("SOAP", Decimal("450.00"))),
                "ValueError: price mismatch for SOAP",
            ),
            (
                "remove some",
                lambda: after_remove("SOAP", 1),
                [("SOAP", 1, Decimal("499.00")), ("RICE-5KG", 1, Decimal("1250.50"))],
            ),
            (
                "remove all",
                lambda: after_remove("SOAP", None),
                [("RICE-5KG", 1, Decimal("1250.50"))],
            ),
            (
                "remove unknown",
                lambda: raised_error_name(lambda: sample_cart().remove("TEA")),
                "KeyError",
            ),
            (
                "negative price",
                lambda: raised_message(lambda: CartItem("X", Decimal("-1"))),
                "ValueError: unit price cannot be negative",
            ),
            (
                "zero quantity",
                lambda: raised_message(lambda: CartItem("X", Decimal("1"), 0)),
                "ValueError: quantity must be at least 1",
            ),
            (
                "float price",
                lambda: raised_message(lambda: CartItem("X", 9.99)),  # type: ignore[arg-type]
                "TypeError: unit_price must be a Decimal, got float",
            ),
            (
                "line_total is a property",
                lambda: type(CartItem.__dict__["line_total"]).__name__,
                "property",
            ),
        ]
    )


# Lab 2.2 -------------------------------------------------------------------------------------


class Animal:
    """Case "diamond": the shared base."""


class Swimmer(Animal):
    """Case "diamond": left branch."""


class Flyer(Animal):
    """Case "diamond": right branch."""


class Duck(Swimmer, Flyer):
    """Case "diamond": joins both branches."""


class Base:
    """Case "services": the concrete base."""


class LoggingMixin:
    """Case "services": logging behaviour."""


class CacheMixin:
    """Case "services": caching behaviour."""


class Service(LoggingMixin, CacheMixin, Base):
    """Case "services": a service built from two mixins and a base."""


class AuditMixin(LoggingMixin):
    """Case "services": a mixin that extends another mixin."""


class AuditedService(AuditMixin, Service):
    """Case "services": the class whose MRO you compute."""


class Persistent:
    """Case "classic": saves itself."""


class Versioned:
    """Case "classic": keeps versions."""


class Searchable:
    """Case "classic": can be searched."""


class Document(Persistent, Versioned):
    """Case "classic": left parent."""


class Index(Persistent, Searchable):
    """Case "classic": right parent."""


class SearchableDocument(Document, Index):
    """Case "classic": the class whose MRO you compute."""


MRO_CASES: dict[str, type] = {
    "diamond": Duck,
    "services": AuditedService,
    "classic": SearchableDocument,
}


def predict_mro(case_name: str) -> list[str]:
    """Return the class names of the case's MRO, computed by hand.

    diamond:  L[Duck] = Duck + merge([Swimmer, Animal, object], [Flyer, Animal, object],
              [Swimmer, Flyer]) -> Swimmer; Animal is in a tail, so Flyer; then Animal, object.
    services: L[AuditedService] = AuditedService + merge([AuditMixin, LoggingMixin, object],
              [Service, LoggingMixin, CacheMixin, Base, object], [AuditMixin, Service])
              -> AuditMixin; LoggingMixin is in a tail, so Service; then LoggingMixin,
              CacheMixin, Base, object.
    classic:  L[SearchableDocument] = SearchableDocument + merge([Document, Persistent,
              Versioned, object], [Index, Persistent, Searchable, object], [Document, Index])
              -> Document; Persistent is in a tail, so Index; Persistent; Versioned; object is
              in a tail, so Searchable; object.
    """
    match case_name:
        case "diamond":
            return ["Duck", "Swimmer", "Flyer", "Animal", "object"]
        case "services":
            return [
                "AuditedService",
                "AuditMixin",
                "Service",
                "LoggingMixin",
                "CacheMixin",
                "Base",
                "object",
            ]
        case "classic":
            return [
                "SearchableDocument",
                "Document",
                "Index",
                "Persistent",
                "Versioned",
                "Searchable",
                "object",
            ]
        case _:
            raise ValueError(f"unknown case: {case_name}")


def mro_names(cls: type) -> list[str]:
    """Class names along cls.__mro__."""
    return [klass.__name__ for klass in cls.__mro__]


def _to_json_value(value: object) -> object:
    """Convert one attribute value into something json.dumps accepts."""
    if isinstance(value, JsonMixin):
        return value.to_dict()
    if isinstance(value, (datetime, date)):  # datetime is a subclass of date
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    return value


class JsonMixin:
    """Adds to_dict() / to_json() to any class whose state lives in instance attributes."""

    def to_dict(self) -> dict[str, Any]:
        """Public attributes as JSON-ready values (nested JsonMixin objects become dicts)."""
        return {
            name: _to_json_value(value)
            for name, value in vars(self).items()
            if not name.startswith("_")
        }

    def to_json(self, **dumps_options: Any) -> str:
        """Serialize to_dict() with json.dumps, forwarding options such as indent."""
        return json.dumps(self.to_dict(), **dumps_options)


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
    """A customer with nested addresses, a last order and private fields."""

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
        self.name = name
        self.joined_at = joined_at
        self.birthday = birthday
        self.addresses = addresses
        self.last_order = last_order
        self.tags = tags
        self.preferences = preferences
        self._password_hash = "pbkdf2$not-for-json"


def make_sample_customer() -> Customer:
    """A fresh customer for the JSON checks."""
    return Customer(
        name="Fatima",
        joined_at=datetime(2026, 1, 15, 9, 30),
        birthday=date(1994, 8, 2),
        addresses=[Address("Pune", "411001"), Address("Goa", "403001")],
        last_order=[LineItem("SOAP", Decimal("49.50"), 2)],
        tags=("vip", "early-adopter"),
        preferences={"newsletter": True, "home": Address("Pune", "411001")},
    )


EXPECTED_CUSTOMER_DICT = {
    "name": "Fatima",
    "joined_at": "2026-01-15T09:30:00",
    "birthday": "1994-08-02",
    "addresses": [{"city": "Pune", "pin_code": "411001"}, {"city": "Goa", "pin_code": "403001"}],
    "last_order": [{"sku": "SOAP", "unit_price": "49.50", "quantity": 2}],
    "tags": ["vip", "early-adopter"],
    "preferences": {"newsletter": True, "home": {"city": "Pune", "pin_code": "411001"}},
}


# Exercise 3: the legacy inheritance tree (given) and the composition refactor.

type SalesRows = list[tuple[str, int]]


class LegacyReport:
    """Legacy base: subclasses pick a format by overriding render()."""

    def __init__(self, title: str, rows: SalesRows) -> None:
        self.title = title
        self.rows = rows

    def render(self) -> str:
        """Subclasses override this."""
        raise NotImplementedError

    def publish(self) -> str:
        """Render and return the report."""
        return self.render()


class CsvReport(LegacyReport):
    """CSV format."""

    def render(self) -> str:
        """Title line, header, one line per row."""
        body = "\n".join(f"{product},{units}" for product, units in self.rows)
        return f"# {self.title}\nproduct,units\n{body}"


class TextReport(LegacyReport):
    """Aligned plain-text format."""

    def render(self) -> str:
        """Title, underline, product left-aligned in 12 columns, units right-aligned in 5."""
        lines = [self.title, "=" * len(self.title)]
        lines += [f"{product:<12}{units:>5}" for product, units in self.rows]
        return "\n".join(lines)


class EmailedCsvReport(CsvReport):
    """CSV report that is also e-mailed."""

    def __init__(self, title: str, rows: SalesRows, outbox: list[tuple[str, str]]) -> None:
        super().__init__(title, rows)
        self.outbox = outbox

    def publish(self) -> str:
        """Render, then append (title, content) to the outbox."""
        content = super().publish()
        self.outbox.append((self.title, content))
        return content


class EmailedTextReport(TextReport):
    """Text report that is also e-mailed (the same code as EmailedCsvReport, duplicated)."""

    def __init__(self, title: str, rows: SalesRows, outbox: list[tuple[str, str]]) -> None:
        super().__init__(title, rows)
        self.outbox = outbox

    def publish(self) -> str:
        """Render, then append (title, content) to the outbox."""
        content = super().publish()
        self.outbox.append((self.title, content))
        return content


class ArchivedEmailedCsvReport(EmailedCsvReport):
    """CSV report that is e-mailed and archived."""

    def __init__(
        self,
        title: str,
        rows: SalesRows,
        outbox: list[tuple[str, str]],
        archive: dict[str, str],
    ) -> None:
        super().__init__(title, rows, outbox)
        self.archive = archive

    def publish(self) -> str:
        """Render, e-mail, then store the content in the archive under the title."""
        content = super().publish()
        self.archive[self.title] = content
        return content


class CsvFormatter:
    """Formats rows as CSV."""

    def format(self, title: str, rows: SalesRows) -> str:
        """Same output as CsvReport.render."""
        body = "\n".join(f"{product},{units}" for product, units in rows)
        return f"# {title}\nproduct,units\n{body}"


class TextFormatter:
    """Formats rows as aligned text."""

    def format(self, title: str, rows: SalesRows) -> str:
        """Same output as TextReport.render."""
        lines = [title, "=" * len(title)]
        lines += [f"{product:<12}{units:>5}" for product, units in rows]
        return "\n".join(lines)


class EmailDelivery:
    """Delivers a report by appending (title, content) to an outbox list."""

    def __init__(self, outbox: list[tuple[str, str]]) -> None:
        self.outbox = outbox

    def deliver(self, title: str, content: str) -> None:
        """Queue the report for e-mail."""
        self.outbox.append((title, content))


class ArchiveDelivery:
    """Delivers a report by storing it in an archive dict under its title."""

    def __init__(self, archive: dict[str, str]) -> None:
        self.archive = archive

    def deliver(self, title: str, content: str) -> None:
        """Store the report."""
        self.archive[title] = content


class Report:
    """A report that has a formatter and any number of deliveries (composition)."""

    def __init__(
        self,
        title: str,
        rows: SalesRows,
        formatter: CsvFormatter | TextFormatter,
        deliveries: Iterable[EmailDelivery | ArchiveDelivery] = (),
    ) -> None:
        self.title = title
        self.rows = rows
        self.formatter = formatter
        self.deliveries = list(deliveries)

    def publish(self) -> str:
        """Format, hand the content to every delivery in order, and return it."""
        content = self.formatter.format(self.title, self.rows)
        for delivery in self.deliveries:
            delivery.deliver(self.title, content)
        return content


SAMPLE_SALES: SalesRows = [("Soap", 120), ("Rice 5 kg", 45), ("Tea", 300)]


def check_lab_2_2() -> None:
    """Run the same checks as the Lab 2.2 check cells in the notebook."""
    print("Exercise 1 — three MROs by hand")
    run_checks(
        [
            (case_name, lambda case_name=case_name: predict_mro(case_name), mro_names(cls))
            for case_name, cls in MRO_CASES.items()
        ]
    )

    print("Exercise 2 — JsonMixin")

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

    print("Exercise 3 — composition instead of inheritance")

    def legacy_outputs() -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
        """Publish through the legacy tree and capture every side effect."""
        outbox: list[tuple[str, str]] = []
        archive: dict[str, str] = {}
        text_content = EmailedTextReport("Weekly sales", SAMPLE_SALES, outbox).publish()
        csv_content = ArchivedEmailedCsvReport(
            "Weekly sales", SAMPLE_SALES, outbox, archive
        ).publish()
        return text_content, csv_content, outbox, archive

    def composed_outputs() -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
        """Publish the same two reports through Report + formatters + deliveries."""
        outbox: list[tuple[str, str]] = []
        archive: dict[str, str] = {}
        text_content = Report(
            "Weekly sales", SAMPLE_SALES, TextFormatter(), [EmailDelivery(outbox)]
        ).publish()
        csv_content = Report(
            "Weekly sales",
            SAMPLE_SALES,
            CsvFormatter(),
            [EmailDelivery(outbox), ArchiveDelivery(archive)],
        ).publish()
        return text_content, csv_content, outbox, archive

    def new_combination() -> tuple[str, dict[str, str]]:
        """Archived text report: a combination the legacy tree has no class for."""
        archive: dict[str, str] = {}
        content = Report(
            "Stock", [("Tea", 7)], TextFormatter(), [ArchiveDelivery(archive)]
        ).publish()
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
                ("Stock\n=====\nTea             7", {"Stock": "Stock\n=====\nTea             7"}),
            ),
            ("Report has no base class", lambda: Report.__bases__, (object,)),
            (
                "deliveries default to none",
                lambda: Report("Q3", [], CsvFormatter()).deliveries,
                [],
            ),
        ]
    )


# Lab 2.3 -------------------------------------------------------------------------------------


class Shape(ABC):
    """Abstract shape: subclasses provide area and perimeter; shapes sort by area."""

    @property
    @abstractmethod
    def area(self) -> float:
        """Area in square units."""

    @abstractmethod
    def perimeter(self) -> float:
        """Perimeter in units."""

    def __lt__(self, other: object) -> bool:
        """Order shapes by area, so sorted() works."""
        if not isinstance(other, Shape):
            return NotImplemented
        return self.area < other.area

    def describe(self) -> str:
        """Template method: one line built from the abstract parts."""
        return f"{type(self).__name__}: area={self.area:.2f}, perimeter={self.perimeter():.2f}"


def _require_positive(*dimensions: float) -> None:
    """Raise ValueError unless every dimension is greater than zero."""
    if any(dimension <= 0 for dimension in dimensions):
        raise ValueError("dimensions must be positive")


class Circle(Shape):
    """A circle."""

    def __init__(self, radius: float) -> None:
        _require_positive(radius)
        self.radius = radius

    @property
    def area(self) -> float:
        """π r²."""
        return pi * self.radius**2

    def perimeter(self) -> float:
        """2 π r."""
        return 2 * pi * self.radius


class Rectangle(Shape):
    """A rectangle."""

    def __init__(self, width: float, height: float) -> None:
        _require_positive(width, height)
        self.width = width
        self.height = height

    @property
    def area(self) -> float:
        """width × height."""
        return self.width * self.height

    def perimeter(self) -> float:
        """2 (width + height)."""
        return 2 * (self.width + self.height)


class Square(Shape):
    """A square (deliberately not a Rectangle subclass, see 2.2.5)."""

    def __init__(self, side: float) -> None:
        _require_positive(side)
        self.side = side

    @property
    def area(self) -> float:
        """side²."""
        return self.side**2

    def perimeter(self) -> float:
        """4 × side."""
        return 4 * self.side


class ReadOnlyView[K, V](Mapping[K, V]):
    """A live, read-only view of another mapping."""

    def __init__(self, data: Mapping[K, V]) -> None:
        self._data = data

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


@runtime_checkable
class SupportsClose(Protocol):
    """Anything with a close() method."""

    def close(self) -> None:
        """Release the resource."""
        ...


def close_all(resources: Iterable[object]) -> tuple[int, list[str]]:
    """Close every resource that supports close(), even if some fail.

    Returns (number closed successfully, ["TypeName: message" for each failure]).
    """
    closed_count = 0
    failures: list[str] = []
    for resource in resources:
        if not isinstance(resource, SupportsClose):
            continue
        try:
            resource.close()
        except Exception as error:
            failures.append(f"{type(resource).__name__}: {error}")
        else:
            closed_count += 1
    return closed_count, failures


class PaymentDeclinedError(Exception):
    """The provider refused the charge; the message says why."""


class PaymentResult(NamedTuple):
    """Outcome of CheckoutService.pay."""

    order_id: str
    provider: str
    status: str  # "paid" or "declined"
    transaction_id: str | None
    message: str


UPI_LIMIT_PAISE = 1_00_000_00  # ₹1,00,000


@runtime_checkable
class PaymentProvider(Protocol):
    """What CheckoutService needs from a payment provider."""

    name: str

    def charge(self, amount_paise: int, token: str) -> str:
        """Charge the amount and return a transaction id, or raise PaymentDeclinedError."""
        ...

    def refund(self, transaction_id: str) -> None:
        """Refund a previous charge; KeyError for an unknown id."""
        ...


class _InMemoryGateway:
    """Shared bookkeeping for the two fake gateways (an implementation detail)."""

    name = "base"

    def __init__(self) -> None:
        self.charges: dict[str, int] = {}
        self.refunded: list[str] = []
        self._next_number = 1

    def _record(self, amount_paise: int) -> str:
        transaction_id = f"{self.name}_{self._next_number:04d}"
        self._next_number += 1
        self.charges[transaction_id] = amount_paise
        return transaction_id

    def refund(self, transaction_id: str) -> None:
        """Move a charge to the refunded list."""
        if transaction_id not in self.charges:
            raise KeyError(transaction_id)
        del self.charges[transaction_id]
        self.refunded.append(transaction_id)


class CardGateway(_InMemoryGateway):
    """Card payments: tokens must start with "tok_"."""

    name = "card"

    def charge(self, amount_paise: int, token: str) -> str:
        """Charge a card token."""
        if amount_paise <= 0:
            raise ValueError("amount must be positive")
        if not token.startswith("tok_"):
            raise PaymentDeclinedError("invalid card token")
        return self._record(amount_paise)


class UpiGateway(_InMemoryGateway):
    """UPI payments: tokens are UPI IDs (contain "@"), limit ₹1,00,000 per payment."""

    name = "upi"

    def charge(self, amount_paise: int, token: str) -> str:
        """Charge a UPI ID."""
        if amount_paise <= 0:
            raise ValueError("amount must be positive")
        if "@" not in token:
            raise PaymentDeclinedError("invalid UPI ID")
        if amount_paise > UPI_LIMIT_PAISE:
            raise PaymentDeclinedError("amount exceeds UPI limit")
        return self._record(amount_paise)


class CheckoutService:
    """Takes payments through any PaymentProvider."""

    def __init__(self, provider: PaymentProvider) -> None:
        self.provider = provider
        self.history: list[PaymentResult] = []

    def pay(self, order_id: str, amount_paise: int, token: str) -> PaymentResult:
        """Charge the provider; a decline becomes a "declined" result instead of an error."""
        try:
            transaction_id = self.provider.charge(amount_paise, token)
        except PaymentDeclinedError as error:
            result = PaymentResult(order_id, self.provider.name, "declined", None, str(error))
        else:
            result = PaymentResult(order_id, self.provider.name, "paid", transaction_id, "")
        self.history.append(result)
        return result

    def refund(self, result: PaymentResult) -> None:
        """Refund a paid result through the same provider."""
        if result.status != "paid" or result.transaction_id is None:
            raise ValueError("only paid orders can be refunded")
        self.provider.refund(result.transaction_id)


def check_lab_2_3() -> None:
    """Run the same checks as the Lab 2.3 check cells in the notebook."""
    print("Exercise 1 — Shape ABC")

    class Triangle(Shape):
        """Forgets perimeter()."""

        @property
        def area(self) -> float:
            return 1.0

    sample_shapes = [Rectangle(3, 4), Circle(1), Square(3), Circle(2)]
    run_checks(
        [
            ("Shape is abstract", lambda: raised_error_name(Shape), "TypeError"),  # type: ignore[abstract]
            ("incomplete subclass", lambda: raised_error_name(Triangle), "TypeError"),  # type: ignore[abstract]
            ("abstract members", lambda: sorted(Shape.__abstractmethods__), ["area", "perimeter"]),
            (
                "sorted by area",
                lambda: [type(shape).__name__ for shape in sorted(sample_shapes)],
                ["Circle", "Square", "Rectangle", "Circle"],
            ),
            ("less than", lambda: (Circle(1) < Square(2), Square(2) < Circle(1)), (True, False)),
            ("describe circle", lambda: Circle(1).describe(), "Circle: area=3.14, perimeter=6.28"),
            (
                "describe rectangle",
                lambda: Rectangle(3, 4).describe(),
                "Rectangle: area=12.00, perimeter=14.00",
            ),
            (
                "describe square",
                lambda: Square(2.5).describe(),
                "Square: area=6.25, perimeter=10.00",
            ),
            ("area is a property", lambda: Square(3).area, 9),
            ("Square is not a Rectangle", lambda: issubclass(Square, Rectangle), False),
            (
                "positive dimensions",
                lambda: raised_message(lambda: Rectangle(0, 2)),
                "ValueError: dimensions must be positive",
            ),
            (
                "compare with non-shape",
                lambda: raised_error_name(lambda: Circle(1) < 5),  # type: ignore[operator]
                "TypeError",
            ),
        ]
    )

    print("Exercise 2 — ReadOnlyView")
    prices = {"soap": 49, "tea": 120}

    def live_update() -> int:
        """Change the wrapped dict and read through the view."""
        backing = {"soap": 49}
        view = ReadOnlyView(backing)
        backing["soap"] = 55
        return view["soap"]

    def try_assign() -> None:
        """Item assignment on the view."""
        view = ReadOnlyView({"soap": 49})
        view["soap"] = 1  # type: ignore[index]

    run_checks(
        [
            ("getitem", lambda: ReadOnlyView(prices)["tea"], 120),
            ("len", lambda: len(ReadOnlyView(prices)), 2),
            ("iteration order", lambda: list(ReadOnlyView(prices)), ["soap", "tea"]),
            (
                "get (free)",
                lambda: (ReadOnlyView(prices).get("rice"), ReadOnlyView(prices).get("rice", 0)),
                (None, 0),
            ),
            (
                "items (free)",
                lambda: list(ReadOnlyView(prices).items()),
                [("soap", 49), ("tea", 120)],
            ),
            (
                "in (free)",
                lambda: ("soap" in ReadOnlyView(prices), "rice" in ReadOnlyView(prices)),
                (True, False),
            ),
            ("== dict (free)", lambda: ReadOnlyView(prices) == {"tea": 120, "soap": 49}, True),
            (
                "missing key",
                lambda: raised_error_name(lambda: ReadOnlyView(prices)["rice"]),
                "KeyError",
            ),
            ("live view", live_update, 55),
            ("no assignment", lambda: raised_error_name(try_assign), "TypeError"),
            ("is a Mapping", lambda: isinstance(ReadOnlyView(prices), Mapping), True),
            (
                "not a MutableMapping",
                lambda: isinstance(ReadOnlyView(prices), MutableMapping),
                False,
            ),
            (
                "only three methods written",
                lambda: sorted(
                    name
                    for name in vars(ReadOnlyView)
                    if name
                    in {
                        "__getitem__",
                        "__iter__",
                        "__len__",
                        "get",
                        "keys",
                        "items",
                        "values",
                        "__contains__",
                    }
                ),
                ["__getitem__", "__iter__", "__len__"],
            ),
        ]
    )

    print("Exercise 3 — SupportsClose")

    class Recorder:
        """Closes cleanly and remembers it; does not inherit from anything."""

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FlakyResource:
        """close() fails."""

        def close(self) -> None:
            raise OSError("disk unplugged")

    def close_mixed() -> tuple[tuple[int, list[str]], bool, bool]:
        """close_all over a mix; also report whether the good resources really closed."""
        buffer = io.StringIO("data")
        recorder = Recorder()
        report = close_all([buffer, "not closable", FlakyResource(), 42, recorder])
        return report, buffer.closed, recorder.closed

    run_checks(
        [
            ("StringIO", lambda: isinstance(io.StringIO(), SupportsClose), True),
            ("plain class, no inheritance", lambda: isinstance(Recorder(), SupportsClose), True),
            ("int", lambda: isinstance(42, SupportsClose), False),
            ("issubclass", lambda: issubclass(FlakyResource, SupportsClose), True),
            ("members", lambda: typing.get_protocol_members(SupportsClose), frozenset({"close"})),
            ("close_all", close_mixed, ((2, ["FlakyResource: disk unplugged"]), True, True)),
            ("generator input", lambda: close_all(Recorder() for _ in range(3)), (3, [])),
            ("empty", lambda: close_all([]), (0, [])),
        ]
    )

    print("Exercise 4 — PaymentProvider")

    class WalletGateway:
        """A third provider written later, without inheriting from anything."""

        name = "wallet"

        def charge(self, amount_paise: int, token: str) -> str:
            return f"wallet-{amount_paise}"

        def refund(self, transaction_id: str) -> None:
            pass

    def card_flow() -> list[PaymentResult]:
        """Two card payments: one paid, one declined."""
        checkout = CheckoutService(CardGateway())
        checkout.pay("ORD-1", 49_900, "tok_visa")
        checkout.pay("ORD-2", 10_000, "4111-1111")
        return checkout.history

    def upi_flow() -> tuple[PaymentResult, PaymentResult, PaymentResult]:
        """UPI: paid, bad ID, over the limit."""
        checkout = CheckoutService(UpiGateway())
        return (
            checkout.pay("ORD-3", 25_000, "asha@okbank"),
            checkout.pay("ORD-4", 25_000, "asha"),
            checkout.pay("ORD-5", UPI_LIMIT_PAISE + 1, "asha@okbank"),
        )

    def refund_flow() -> tuple[dict[str, int], list[str]]:
        """Pay twice, refund the first."""
        gateway = UpiGateway()
        checkout = CheckoutService(gateway)
        first = checkout.pay("ORD-6", 1_000, "ravi@okbank")
        checkout.pay("ORD-7", 2_000, "ravi@okbank")
        checkout.refund(first)
        return gateway.charges, gateway.refunded

    def refund_declined() -> None:
        """Refunding a declined payment."""
        checkout = CheckoutService(CardGateway())
        checkout.refund(checkout.pay("ORD-8", 100, "bad-token"))

    run_checks(
        [
            ("card satisfies", lambda: isinstance(CardGateway(), PaymentProvider), True),
            ("upi satisfies", lambda: isinstance(UpiGateway(), PaymentProvider), True),
            ("wallet satisfies", lambda: isinstance(WalletGateway(), PaymentProvider), True),
            ("str does not", lambda: isinstance("card", PaymentProvider), False),
            (
                "members",
                lambda: sorted(typing.get_protocol_members(PaymentProvider)),
                ["charge", "name", "refund"],
            ),
            (
                "issubclass refused (data member)",
                lambda: raised_error_name(lambda: issubclass(CardGateway, PaymentProvider)),
                "TypeError",
            ),
            (
                "card flow",
                card_flow,
                [
                    PaymentResult("ORD-1", "card", "paid", "card_0001", ""),
                    PaymentResult("ORD-2", "card", "declined", None, "invalid card token"),
                ],
            ),
            (
                "upi flow",
                upi_flow,
                (
                    PaymentResult("ORD-3", "upi", "paid", "upi_0001", ""),
                    PaymentResult("ORD-4", "upi", "declined", None, "invalid UPI ID"),
                    PaymentResult("ORD-5", "upi", "declined", None, "amount exceeds UPI limit"),
                ),
            ),
            ("refund", refund_flow, ({"upi_0002": 2_000}, ["upi_0001"])),
            (
                "refund declined",
                lambda: raised_message(refund_declined),
                "ValueError: only paid orders can be refunded",
            ),
            (
                "unknown refund id",
                lambda: raised_error_name(lambda: CardGateway().refund("card_9999")),
                "KeyError",
            ),
            (
                "bad amount is a bug, not a decline",
                lambda: raised_error_name(
                    lambda: CheckoutService(CardGateway()).pay("ORD-9", 0, "tok_x")
                ),
                "ValueError",
            ),
            (
                "third provider works",
                lambda: CheckoutService(WalletGateway()).pay("ORD-10", 500, "w"),
                PaymentResult("ORD-10", "wallet", "paid", "wallet-500", ""),
            ),
        ]
    )


# Lab 2.4 -------------------------------------------------------------------------------------


def set_attribute(target: object, attribute_name: str, value: object) -> None:
    """`target.attribute_name = value` as a call, for use inside raised_error_name(lambda: ...)."""
    setattr(target, attribute_name, value)


class CurrencyMismatchError(ValueError):
    """Two Money values in different currencies were combined or compared."""


CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}


@functools.total_ordering
class Money:
    """An immutable amount of money in one currency (the shared Phase 2 value type)."""

    __slots__ = ("_amount", "_currency")

    def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
        if isinstance(amount, float):
            raise TypeError("amount must be Decimal, int or str, not float")
        if not (len(currency) == 3 and currency.isalpha() and currency.isupper()):
            raise ValueError(f"invalid currency code: {currency!r}")
        self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
        self._currency = currency

    @property
    def amount(self) -> Decimal:
        """The amount, rounded to the paisa."""
        return self._amount

    @property
    def currency(self) -> str:
        """Three-letter ISO currency code."""
        return self._currency

    def __repr__(self) -> str:
        return f"Money({str(self._amount)!r}, {self._currency!r})"

    def __str__(self) -> str:
        return f"{self._currency} {self._amount:,.2f}"

    def __format__(self, spec: str) -> str:
        if spec == "":
            return str(self)
        if spec == "symbol":
            symbol = CURRENCY_SYMBOLS.get(self._currency, self._currency + " ")
            return f"{symbol}{self._amount:,.2f}"
        return f"{self._currency} {format(self._amount, spec)}"

    def _same_currency(self, other: Money) -> None:
        """Raise CurrencyMismatchError unless other uses this currency."""
        if other._currency != self._currency:
            raise CurrencyMismatchError(f"currency mismatch: {self._currency} vs {other._currency}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return (self._amount, self._currency) == (other._amount, other._currency)

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self._amount < other._amount

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self._amount + other._amount, self._currency)

    def __radd__(self, other: object) -> Money:
        if isinstance(other, int) and not isinstance(other, bool) and other == 0:
            return self  # sum() starts from 0
        return NotImplemented

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self._amount - other._amount, self._currency)

    def __mul__(self, factor: object) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, (int, Decimal)):
            return NotImplemented
        return Money(self._amount * factor, self._currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self._amount, self._currency)

    def __abs__(self) -> Money:
        return Money(abs(self._amount), self._currency)

    def __bool__(self) -> bool:
        return bool(self._amount)


class Vector2D:
    """An immutable 2-D vector."""

    __slots__ = ("_x", "_y")

    def __init__(self, x: float, y: float) -> None:
        self._x = x
        self._y = y

    @property
    def x(self) -> float:
        """Horizontal component."""
        return self._x

    @property
    def y(self) -> float:
        """Vertical component."""
        return self._y

    def __repr__(self) -> str:
        return f"Vector2D({self._x!r}, {self._y!r})"

    def __iter__(self) -> Iterator[float]:
        yield self._x
        yield self._y

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vector2D):
            return NotImplemented
        return (self._x, self._y) == (other._x, other._y)

    def __hash__(self) -> int:
        return hash((self._x, self._y))

    def __add__(self, other: object) -> Vector2D:
        if not isinstance(other, Vector2D):
            return NotImplemented
        return Vector2D(self._x + other._x, self._y + other._y)

    def __sub__(self, other: object) -> Vector2D:
        if not isinstance(other, Vector2D):
            return NotImplemented
        return Vector2D(self._x - other._x, self._y - other._y)

    def __mul__(self, scalar: object) -> Vector2D:
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return Vector2D(self._x * scalar, self._y * scalar)

    __rmul__ = __mul__

    def __neg__(self) -> Vector2D:
        return Vector2D(-self._x, -self._y)

    def __abs__(self) -> float:
        return math.hypot(self._x, self._y)

    def __bool__(self) -> bool:
        return bool(self._x or self._y)

    def __matmul__(self, other: object) -> float:
        if not isinstance(other, Vector2D):
            return NotImplemented
        return self._x * other._x + self._y * other._y


class Playlist:
    """A named, ordered list of songs."""

    def __init__(self, name: str, songs: Iterable[str] = ()) -> None:
        self.name = name
        self._songs = list(songs)

    def __repr__(self) -> str:
        return f"Playlist({self.name!r}, {self._songs!r})"

    def __len__(self) -> int:
        return len(self._songs)

    def __getitem__(self, index: int | slice) -> str | Playlist:
        if isinstance(index, slice):
            return Playlist(self.name, self._songs[index])
        return self._songs[index]

    def __setitem__(self, index: int | slice, value: Any) -> None:
        self._songs[index] = value

    def __delitem__(self, index: int | slice) -> None:
        del self._songs[index]

    def __contains__(self, song: object) -> bool:
        return song in self._songs

    def __iter__(self) -> Iterator[str]:
        return iter(self._songs)

    def __reversed__(self) -> Iterator[str]:
        return reversed(self._songs)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Playlist):
            return NotImplemented
        return (self.name, self._songs) == (other.name, other._songs)


class CaseInsensitiveDict(UserDict[str, str]):
    """HTTP-header style dict: keys compare without case."""

    @staticmethod
    def _fold(key: object) -> str:
        if not isinstance(key, str):
            raise TypeError("keys must be str")
        return key.casefold()

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(self._fold(key), value)

    def __getitem__(self, key: str) -> str:
        return super().__getitem__(self._fold(key))

    def __delitem__(self, key: str) -> None:
        super().__delitem__(self._fold(key))

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.casefold() in self.data


class RateLimiter:
    """Calling the limiter asks: may I make one more call now?"""

    def __init__(
        self,
        max_calls: int,
        period_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._clock = clock
        self._call_times: deque[float] = deque()

    def _forget_old_calls(self, now: float) -> None:
        while self._call_times and now - self._call_times[0] >= self.period_seconds:
            self._call_times.popleft()

    def remaining(self) -> int:
        """How many calls are still allowed right now."""
        self._forget_old_calls(self._clock())
        return self.max_calls - len(self._call_times)

    def __call__(self) -> bool:
        now = self._clock()
        self._forget_old_calls(now)
        if len(self._call_times) >= self.max_calls:
            return False
        self._call_times.append(now)
        return True

    def __repr__(self) -> str:
        return f"RateLimiter(max_calls={self.max_calls!r}, period_seconds={self.period_seconds!r})"


class Inventory:
    """Quantities on hand, keyed by SKU."""

    def __init__(self, stock: Mapping[str, int] | None = None) -> None:
        self._stock: dict[str, int] = {}
        for sku, quantity in (stock or {}).items():
            self[sku] = quantity

    def __getitem__(self, sku: str) -> int:
        return self._stock[sku]

    def __setitem__(self, sku: str, quantity: int) -> None:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise ValueError("quantity must be a non-negative int")
        self._stock[sku] = quantity

    def __delitem__(self, sku: str) -> None:
        del self._stock[sku]

    def __len__(self) -> int:
        return len(self._stock)

    def __contains__(self, sku: object) -> bool:
        return sku in self._stock

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._stock))

    def __bool__(self) -> bool:
        return bool(self._stock)

    def add(self, sku: str, quantity: int) -> None:
        """Increase stock; a new SKU starts at 0."""
        self[sku] = self._stock.get(sku, 0) + quantity

    def remove(self, sku: str, quantity: int) -> None:
        """Decrease stock, refusing to go below zero."""
        have = self._stock.get(sku, 0)
        if quantity > have:
            raise ValueError(f"not enough {sku}: have {have}, need {quantity}")
        self[sku] = have - quantity

    @property
    def total_units(self) -> int:
        """Sum of all quantities."""
        return sum(self._stock.values())

    def __add__(self, other: object) -> Inventory:
        if not isinstance(other, Inventory):
            return NotImplemented
        merged = Inventory(self._stock)
        for sku in other:
            merged.add(sku, other[sku])
        return merged

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Inventory):
            return NotImplemented
        return self._stock == other._stock

    def __repr__(self) -> str:
        return f"Inventory({dict(sorted(self._stock.items()))!r})"


def check_lab_2_4() -> None:
    """Run the same checks as the Lab 2.4 check cells in the notebook."""
    print("Exercise 1 — an immutable Money")

    def money_errors() -> list[str]:
        """Messages for the constructor and mismatch errors."""
        return [
            raised_message(lambda: Money(1.5)),
            raised_message(lambda: Money(1, "inr")),
            raised_message(lambda: Money(1) + Money(1, "USD")),
            raised_message(lambda: Money(1) < Money(1, "USD")),
        ]

    run_checks(
        [
            ("rounds to paise", lambda: Money("10.005").amount, Decimal("10.01")),
            (
                "int and str amounts",
                lambda: (Money(10).amount, Money("2.5").currency),
                (Decimal("10.00"), "INR"),
            ),
            (
                "error messages",
                money_errors,
                [
                    "TypeError: amount must be Decimal, int or str, not float",
                    "ValueError: invalid currency code: 'inr'",
                    "CurrencyMismatchError: currency mismatch: INR vs USD",
                    "CurrencyMismatchError: currency mismatch: INR vs USD",
                ],
            ),
            (
                "read-only amount",
                lambda: raised_error_name(lambda: set_attribute(Money(1), "amount", 5)),
                "AttributeError",
            ),
            (
                "no new attributes",
                lambda: raised_error_name(lambda: set_attribute(Money(1), "note", "x")),
                "AttributeError",
            ),
            ("repr", lambda: repr(Money("1234.5")), "Money('1234.50', 'INR')"),
            ("str", lambda: str(Money("1234.5", "USD")), "USD 1,234.50"),
            (
                "format",
                lambda: f"{Money('1234.5'):symbol}|{Money(7, 'USD'):symbol}|{Money(1234):,.0f}",
                "₹1,234.50|$7.00|INR 1,234",
            ),
            (
                "equality",
                lambda: (
                    Money(10) == Money("10.00"),
                    Money(10) == Money(10, "USD"),
                    Money(10) == 10,
                ),
                (True, False, False),
            ),
            ("hash", lambda: len({Money(10), Money("10.0"), Money(10, "USD")}), 2),
            (
                "ordering",
                lambda: (
                    Money(5) < Money(7),
                    Money(7) <= Money(7),
                    Money(9) > Money(7),
                    Money(1) >= Money(2),
                ),
                (True, True, True, False),
            ),
            (
                "sorted and max",
                lambda: [
                    str(money)
                    for money in [*sorted([Money(3), Money(1), Money(2)]), max(Money(3), Money(9))]
                ],
                ["INR 1.00", "INR 2.00", "INR 3.00", "INR 9.00"],
            ),
            ("compare with int", lambda: raised_error_name(lambda: Money(5) < 5), "TypeError"),
            (
                "add and subtract",
                lambda: (str(Money("10.50") + Money("4.75")), str(Money(10) - Money("12.5"))),
                ("INR 15.25", "INR -2.50"),
            ),
            ("sum()", lambda: str(sum([Money(100), Money("49.99"), Money("0.01")])), "INR 150.00"),
            ("0 + money", lambda: repr(0 + Money(5)), "Money('5.00', 'INR')"),
            ("other int", lambda: raised_error_name(lambda: Money(5) + 1), "TypeError"),
            (
                "multiply",
                lambda: (
                    str(Money("19.99") * 3),
                    str(2 * Money(5)),
                    str(Money(10) * Decimal("0.125")),
                ),
                ("INR 59.97", "INR 10.00", "INR 1.25"),
            ),
            ("float factor", lambda: raised_error_name(lambda: Money(10) * 1.5), "TypeError"),
            ("money factor", lambda: raised_error_name(lambda: Money(10) * Money(2)), "TypeError"),
            (
                "neg and abs",
                lambda: (str(-Money(5)), str(abs(Money(-5, "EUR")))),
                ("INR -5.00", "EUR 5.00"),
            ),
            ("bool", lambda: (bool(Money(0)), bool(Money("0.01"))), (False, True)),
        ]
    )
    print("Exercise 2 — Vector2D")
    run_checks(
        [
            ("repr", lambda: repr(Vector2D(3, 4)), "Vector2D(3, 4)"),
            ("repr floats", lambda: repr(Vector2D(1.5, -2.0)), "Vector2D(1.5, -2.0)"),
            (
                "read-only",
                lambda: raised_error_name(lambda: set_attribute(Vector2D(1, 2), "x", 5)),
                "AttributeError",
            ),
            (
                "equality and hash",
                lambda: (Vector2D(1, 2) == Vector2D(1, 2), len({Vector2D(1, 2), Vector2D(1, 2)})),
                (True, 1),
            ),
            ("not equal to tuple", lambda: Vector2D(1, 2) == (1, 2), False),
            ("unpacking", lambda: tuple(Vector2D(7, 8)), (7, 8)),
            (
                "add and subtract",
                lambda: (
                    repr(Vector2D(1, 2) + Vector2D(3, 4)),
                    repr(Vector2D(1, 2) - Vector2D(3, 4)),
                ),
                ("Vector2D(4, 6)", "Vector2D(-2, -2)"),
            ),
            (
                "scalar both sides",
                lambda: (repr(Vector2D(1, 2) * 3), repr(0.5 * Vector2D(4, 6))),
                ("Vector2D(3, 6)", "Vector2D(2.0, 3.0)"),
            ),
            ("negation", lambda: repr(-Vector2D(1, -2)), "Vector2D(-1, 2)"),
            ("abs", lambda: abs(Vector2D(3, 4)), 5.0),
            ("bool", lambda: (bool(Vector2D(0, 0)), bool(Vector2D(0, 1))), (False, True)),
            ("dot product", lambda: Vector2D(1, 2) @ Vector2D(3, 4), 11),
            ("add a number", lambda: raised_error_name(lambda: Vector2D(1, 2) + 5), "TypeError"),
            (
                "vector * vector",
                lambda: raised_error_name(lambda: Vector2D(1, 2) * Vector2D(1, 2)),
                "TypeError",
            ),
        ]
    )
    print("Exercise 3 — Playlist with slicing")
    SONGS = ["Kun Faya Kun", "Ilahi", "Kabira", "Safarnama", "Raabta"]

    def playlist_edits() -> Playlist:
        """Replace, delete and slice-delete."""
        road_trip = Playlist("Road trip", SONGS)
        road_trip[0] = "Patakha Guddi"
        del road_trip[-1]
        del road_trip[1:3]
        return road_trip

    def keeps_own_copy() -> list[str]:
        """Changing the source list must not change the playlist."""
        source = ["A", "B"]
        playlist = Playlist("Copy", source)
        source.append("C")
        return list(playlist)

    run_checks(
        [
            ("len", lambda: len(Playlist("Road trip", SONGS)), 5),
            (
                "index",
                lambda: (Playlist("Road trip", SONGS)[0], Playlist("Road trip", SONGS)[-1]),
                ("Kun Faya Kun", "Raabta"),
            ),
            (
                "index error",
                lambda: raised_error_name(lambda: Playlist("Road trip", SONGS)[5]),
                "IndexError",
            ),
            ("slice type", lambda: type(Playlist("Road trip", SONGS)[1:3]).__name__, "Playlist"),
            (
                "slice content",
                lambda: repr(Playlist("Road trip", SONGS)[1:3]),
                "Playlist('Road trip', ['Ilahi', 'Kabira'])",
            ),
            (
                "step slice",
                lambda: list(Playlist("Road trip", SONGS)[::2]),
                ["Kun Faya Kun", "Kabira", "Raabta"],
            ),
            (
                "contains",
                lambda: (
                    "Kabira" in Playlist("Road trip", SONGS),
                    "Tum Hi Ho" in Playlist("Road trip", SONGS),
                ),
                (True, False),
            ),
            ("reversed", lambda: list(reversed(Playlist("x", ["A", "B", "C"]))), ["C", "B", "A"]),
            ("has __reversed__", lambda: "__reversed__" in vars(Playlist), True),
            (
                "edits",
                lambda: repr(playlist_edits()),
                "Playlist('Road trip', ['Patakha Guddi', 'Safarnama'])",
            ),
            ("own copy", keeps_own_copy, ["A", "B"]),
            ("equality uses name", lambda: Playlist("A", ["x"]) == Playlist("B", ["x"]), False),
            (
                "repr",
                lambda: repr(Playlist("Road trip", ["A", "B"])),
                "Playlist('Road trip', ['A', 'B'])",
            ),
        ]
    )
    print("Exercise 4 — CaseInsensitiveDict(UserDict)")

    def header_session() -> tuple[object, ...]:
        """Exercise every inherited method."""
        headers = CaseInsensitiveDict({"Content-Type": "text/html"}, Accept="*/*")
        headers.update({"ACCEPT": "application/json"})
        headers.setdefault("X-Request-Id", "abc123")
        headers.setdefault("x-request-id", "ignored")
        popped = headers.pop("CONTENT-TYPE")
        return popped, headers.get("accept"), headers.get("missing", "-"), sorted(headers)

    run_checks(
        [
            (
                "getitem ignores case",
                lambda: CaseInsensitiveDict({"Content-Type": "text/html"})["content-TYPE"],
                "text/html",
            ),
            ("contains ignores case", lambda: "ACCEPT" in CaseInsensitiveDict(accept="*/*"), True),
            (
                "one key per spelling",
                lambda: len(CaseInsensitiveDict({"Accept": "a", "ACCEPT": "b"})),
                1,
            ),
            ("keys case-folded", lambda: list(CaseInsensitiveDict({"Accept": "a"})), ["accept"]),
            (
                "inherited methods",
                header_session,
                ("text/html", "application/json", "-", ["accept", "x-request-id"]),
            ),
            (
                "delete",
                lambda: raised_error_name(
                    lambda: CaseInsensitiveDict(Accept="a").__delitem__("ACCEPT")
                ),
                "no error",
            ),
            (
                "missing key",
                lambda: raised_error_name(lambda: CaseInsensitiveDict()["accept"]),
                "KeyError",
            ),
            (
                "str keys only",
                lambda: raised_message(lambda: CaseInsensitiveDict({1: "a"})),
                "TypeError: keys must be str",
            ),
            (
                "copy keeps type",
                lambda: type(CaseInsensitiveDict(a="1").copy()).__name__,
                "CaseInsensitiveDict",
            ),
            ("is a UserDict", lambda: isinstance(CaseInsensitiveDict(), UserDict), True),
            (
                "is a MutableMapping",
                lambda: isinstance(CaseInsensitiveDict(), MutableMapping),
                True,
            ),
        ]
    )
    print("Exercise 5 — a callable RateLimiter")

    class ManualClock:
        """A clock that only moves when told to."""

        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    def limiter_timeline() -> list[object]:
        """Three calls allowed per 10 s; record answers over time."""
        clock = ManualClock()
        limiter = RateLimiter(3, 10, clock=clock)
        answers: list[object] = [limiter(), limiter(), limiter(), limiter(), limiter.remaining()]
        clock.now = 9.9
        answers.append(limiter())
        clock.now = 10.0
        answers.extend([limiter.remaining(), limiter(), limiter()])
        return answers

    run_checks(
        [
            ("callable", lambda: callable(RateLimiter(1, 1)), True),
            ("timeline", limiter_timeline, [True, True, True, False, 0, False, 3, True, True]),
            ("remaining at start", lambda: RateLimiter(5, 60, clock=ManualClock()).remaining(), 5),
            (
                "repr",
                lambda: repr(RateLimiter(3, 10)),
                "RateLimiter(max_calls=3, period_seconds=10)",
            ),
            (
                "max_calls",
                lambda: raised_message(lambda: RateLimiter(0, 10)),
                "ValueError: max_calls must be at least 1",
            ),
            (
                "period",
                lambda: raised_message(lambda: RateLimiter(1, 0)),
                "ValueError: period_seconds must be positive",
            ),
        ]
    )
    print("Exercise 6 — an Inventory keyed by SKU")

    def stock_session() -> Inventory:
        """Add, remove, set and delete."""
        inventory = Inventory({"TEA-500": 2})
        inventory.add("PEN-01", 10)
        inventory.add("TEA-500", 3)
        inventory.remove("PEN-01", 4)
        inventory["MUG-02"] = 1
        del inventory["MUG-02"]
        return inventory

    def merge_leaves_operands() -> tuple[str, str]:
        """first + second must build a new Inventory; return both reprs."""
        first = Inventory({"A": 1})
        merged = first + Inventory({"A": 1})
        return repr(merged), repr(first)

    run_checks(
        [
            ("session", lambda: repr(stock_session()), "Inventory({'PEN-01': 6, 'TEA-500': 5})"),
            ("getitem", lambda: Inventory({"PEN-01": 6})["PEN-01"], 6),
            ("unknown sku", lambda: raised_error_name(lambda: Inventory()["NOPE"]), "KeyError"),
            (
                "sorted iteration",
                lambda: list(Inventory({"TEA-500": 1, "MUG-02": 0, "PEN-01": 3})),
                ["MUG-02", "PEN-01", "TEA-500"],
            ),
            (
                "len, in, bool",
                lambda: (len(Inventory({"A": 1})), "A" in Inventory({"A": 1}), bool(Inventory())),
                (1, True, False),
            ),
            (
                "bad quantity",
                lambda: raised_message(lambda: Inventory().__setitem__("A", -1)),
                "ValueError: quantity must be a non-negative int",
            ),
            (
                "not an int",
                lambda: raised_message(lambda: Inventory({"A": 1.5})),
                "ValueError: quantity must be a non-negative int",
            ),
            (
                "not enough",
                lambda: raised_message(lambda: Inventory({"PEN-01": 2}).remove("PEN-01", 5)),
                "ValueError: not enough PEN-01: have 2, need 5",
            ),
            ("total_units", lambda: Inventory({"A": 2, "B": 3}).total_units, 5),
            (
                "merge with +",
                lambda: repr(Inventory({"A": 2, "B": 1}) + Inventory({"B": 4, "C": 1})),
                "Inventory({'A': 2, 'B': 5, 'C': 1})",
            ),
            (
                "+ leaves operands alone",
                merge_leaves_operands,
                ("Inventory({'A': 2})", "Inventory({'A': 1})"),
            ),
            ("+ with dict", lambda: raised_error_name(lambda: Inventory() + {"A": 1}), "TypeError"),
            (
                "repr",
                lambda: repr(Inventory({"TEA-500": 2, "PEN-01": 5})),
                "Inventory({'PEN-01': 5, 'TEA-500': 2})",
            ),
        ]
    )


# Lab 2.5 -------------------------------------------------------------------------------------


class MyProperty:
    """A pure-Python property."""

    def __init__(
        self,
        fget: Callable[[Any], Any] | None = None,
        fset: Callable[[Any, Any], None] | None = None,
        fdel: Callable[[Any], None] | None = None,
        doc: str | None = None,
    ) -> None:
        self.fget = fget
        self.fset = fset
        self.fdel = fdel
        self.__doc__ = doc if doc is not None else getattr(fget, "__doc__", None)
        self.name = getattr(fget, "__name__", "<unnamed>")

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        if self.fget is None:
            raise AttributeError(f"property {self.name!r} has no getter")
        return self.fget(instance)

    def __set__(self, instance: object, value: object) -> None:
        if self.fset is None:
            raise AttributeError(f"property {self.name!r} has no setter")
        self.fset(instance, value)

    def __delete__(self, instance: object) -> None:
        if self.fdel is None:
            raise AttributeError(f"property {self.name!r} has no deleter")
        self.fdel(instance)

    def _copy(self, **changes: Any) -> MyProperty:
        """A new MyProperty with some functions replaced."""
        functions = {"fget": self.fget, "fset": self.fset, "fdel": self.fdel} | changes
        new_property = type(self)(**functions, doc=self.__doc__)
        new_property.name = self.name
        return new_property

    def getter(self, fget: Callable[[Any], Any]) -> MyProperty:
        """Return a copy with a new getter."""
        return self._copy(fget=fget)

    def setter(self, fset: Callable[[Any, Any], None]) -> MyProperty:
        """Return a copy with a setter."""
        return self._copy(fset=fset)

    def deleter(self, fdel: Callable[[Any], None]) -> MyProperty:
        """Return a copy with a deleter."""
        return self._copy(fdel=fdel)


class _StoredInInstance:
    """Shared base for Typed and Bounded: the value lives in instance.__dict__[name]."""

    name = "<unnamed>"

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        try:
            return instance.__dict__[self.name]
        except KeyError:
            raise AttributeError(f"{self.name} has not been set") from None

    def validate(self, value: Any) -> None:
        """Subclasses raise for bad values."""

    def __set__(self, instance: object, value: Any) -> None:
        self.validate(value)
        instance.__dict__[self.name] = value


class Typed(_StoredInInstance):
    """Only accepts instances of expected_type."""

    def __init__(self, expected_type: type) -> None:
        self.expected_type = expected_type

    def validate(self, value: Any) -> None:
        if not isinstance(value, self.expected_type):
            raise TypeError(
                f"{self.name} must be {self.expected_type.__name__}, got {type(value).__name__}"
            )


class Bounded(_StoredInInstance):
    """Keeps a value between optional bounds."""

    def __init__(self, minimum: float | None = None, maximum: float | None = None) -> None:
        self.minimum = minimum
        self.maximum = maximum

    def validate(self, value: Any) -> None:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.name} must be >= {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.name} must be <= {self.maximum}")


class LazyAttribute:
    """Compute once per instance, then behave like a normal attribute."""

    def __init__(self, func: Callable[[Any], Any]) -> None:
        self.func = func
        self.name = func.__name__
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        value = self.func(instance)
        instance.__dict__[self.name] = value  # later reads skip this non-data descriptor
        return value


class PluginBase:
    """Subclasses register themselves by name."""

    registry: dict[str, type[PluginBase]] = {}
    plugin_name: str

    def __init_subclass__(cls, /, *, plugin_name: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name = plugin_name or cls.__name__.lower()
        if name in PluginBase.registry:
            raise ValueError(f"duplicate plugin name: {name!r}")
        cls.plugin_name = name
        PluginBase.registry[name] = cls

    @classmethod
    def create(cls, name: str, *args: Any, **kwargs: Any) -> PluginBase:
        """Instantiate a registered plugin (KeyError for unknown names)."""
        return PluginBase.registry[name](*args, **kwargs)

    @classmethod
    def available(cls) -> list[str]:
        """Sorted plugin names."""
        return sorted(PluginBase.registry)


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
        self.sql_type = sql_type
        self.python_type = python_type
        self.primary_key = primary_key
        self.nullable = nullable
        self.name = "<unnamed>"

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return instance.__dict__.get(self.name)

    def __set__(self, instance: object, value: Any) -> None:
        if value is None:
            if not self.nullable:
                raise ValueError(f"{self.name} cannot be NULL")
        elif not isinstance(value, self.python_type):
            raise TypeError(f"{self.name} must be {self.python_type.__name__}")
        instance.__dict__[self.name] = value

    def column_sql(self) -> str:
        """Column definition for CREATE TABLE."""
        if self.primary_key:
            return f"{self.name} {self.sql_type} PRIMARY KEY"
        if not self.nullable:
            return f"{self.name} {self.sql_type} NOT NULL"
        return f"{self.name} {self.sql_type}"


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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.fields = {name: value for name, value in vars(cls).items() if isinstance(value, Field)}
        cls.table_name = vars(cls).get("table_name") or cls.__name__.lower() + "s"

    def __init__(self, **values: Any) -> None:
        for name in values:
            if name not in self.fields:
                raise TypeError(f"unknown field: {name}")
        for name in self.fields:
            setattr(self, name, values.get(name))

    @classmethod
    def create_table_sql(cls) -> str:
        """CREATE TABLE statement for this model."""
        columns = ", ".join(field.column_sql() for field in cls.fields.values())
        return f"CREATE TABLE {cls.table_name} ({columns})"

    def insert_sql(self) -> tuple[str, tuple[Any, ...]]:
        """Parameterized INSERT statement and its values."""
        names = list(self.fields)
        placeholders = ", ".join("?" for _ in names)
        statement = f"INSERT INTO {self.table_name} ({', '.join(names)}) VALUES ({placeholders})"
        return statement, tuple(getattr(self, name) for name in names)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.fields)
        return f"{type(self).__name__}({pairs})"


def check_lab_2_5() -> None:
    """Run the same checks as the Lab 2.5 check cells in the notebook."""
    print("Exercise 1 — rebuild property")

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
                lambda: raised_message(
                    lambda: set_attribute(make_thermostat_class()(), "serial", "x")
                ),
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
    print("Exercise 2 — Typed and Bounded descriptors")

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
                    type(vars(make_booking_class())[name]).__name__
                    for name in ("guest_name", "guests")
                ],
                ["Typed", "Bounded"],
            ),
            (
                "data descriptors",
                lambda: (
                    inspect.isdatadescriptor(Typed(int)) and inspect.isdatadescriptor(Bounded(0))
                ),
                True,
            ),
        ]
    )
    print("Exercise 3 — a caching LazyAttribute")

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
    print("Exercise 4 — a PluginBase registry with __init_subclass__")

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
    print("Exercise 5 — a mini ORM with Field descriptors")

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


# Lab 2.6 -------------------------------------------------------------------------------------
# The notebook calls exercise 1's classes Address and Customer; here they are ValidatedAddress
# and ValidatedCustomer so they do not replace Lab 2.2's Address and Customer in this module.


@dataclass(frozen=True)
class ValidatedAddress:
    """A postal address (value object): stripped, with a six-digit PIN code."""

    street: str
    city: str
    pin_code: str

    def __post_init__(self) -> None:
        street, city = self.street.strip(), self.city.strip()
        if not street or not city:
            raise ValueError("street and city are required")
        if not (len(self.pin_code) == 6 and self.pin_code.isdigit() and self.pin_code[0] != "0"):
            raise ValueError(f"invalid PIN code: {self.pin_code!r}")
        object.__setattr__(self, "street", street)
        object.__setattr__(self, "city", city)


@dataclass
class ValidatedCustomer:
    """A customer (entity): equal by customer_id only."""

    customer_id: int
    name: str = field(compare=False)
    email: str = field(compare=False)
    addresses: list[ValidatedAddress] = field(default_factory=list, compare=False)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name is required")
        cleaned_email = self.email.strip().lower()
        local_part, at_sign, domain = cleaned_email.partition("@")
        if not local_part or not at_sign or "@" in domain or "." not in domain:
            raise ValueError(f"invalid email: {self.email!r}")
        self.email = cleaned_email

    def add_address(self, address: ValidatedAddress) -> bool:
        """Append the address unless an equal one is already there."""
        if address in self.addresses:
            return False
        self.addresses.append(address)
        return True


ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "cancelled"}),
    "paid": frozenset({"shipped", "cancelled"}),
    "shipped": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}


class OrderStatus(StrEnum):
    """Order lifecycle with allowed transitions."""

    PENDING = auto()
    PAID = auto()
    SHIPPED = auto()
    DELIVERED = auto()
    CANCELLED = auto()

    @classmethod
    def _missing_(cls, value: object) -> OrderStatus | None:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            for member in cls:
                if member.value == cleaned:
                    return member
        return None

    def can_transition_to(self, target: OrderStatus) -> bool:
        """Is target an allowed next status?"""
        return target.value in ORDER_TRANSITIONS[self.value]

    def transition_to(self, target: OrderStatus) -> OrderStatus:
        """Return target, or raise ValueError for a forbidden move."""
        if not self.can_transition_to(target):
            raise ValueError(f"cannot go from {self} to {target}")
        return target

    @property
    def is_final(self) -> bool:
        """No transitions out of this status."""
        return not ORDER_TRANSITIONS[self.value]


class Permission(Flag):
    """Access rights; the combined names are aliases."""

    READ = auto()
    WRITE = auto()
    DELETE = auto()
    SHARE = auto()
    VIEWER = READ
    EDITOR = READ | WRITE
    OWNER = READ | WRITE | DELETE | SHARE


def has_permission(granted: Permission, required: Permission) -> bool:
    """True only if every bit of required is in granted."""
    return required & granted == required


def parse_permissions(text: str) -> Permission:
    """'read, Write' -> Permission.READ | Permission.WRITE."""
    result = Permission(0)
    for raw_name in text.split(","):
        name = raw_name.strip().lower()
        if not name:
            continue
        try:
            result |= Permission[name.upper()]
        except KeyError:
            raise ValueError(f"unknown permission: {name!r}") from None
    return result


def permission_names(permission: Permission) -> list[str]:
    """Single-bit member names in definition order."""
    return [member.name for member in permission if member.name is not None]


class EventBus:
    """Dispatch events to handlers subscribed to their class or a base class."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[Any], object]]] = {}

    def subscribe(self, event_type: type, handler: Callable[[Any], object]) -> Callable[[], None]:
        """Register handler; return a function that unsubscribes it."""
        self._handlers.setdefault(event_type, []).append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def on(self, event_type: type) -> Callable[[Callable[[Any], object]], Callable[[Any], object]]:
        """Decorator form of subscribe."""

        def register(handler: Callable[[Any], object]) -> Callable[[Any], object]:
            self.subscribe(event_type, handler)
            return handler

        return register

    def publish(self, event: object) -> int:
        """Call every matching handler (most specific class first); group failures."""
        called_count = 0
        errors: list[Exception] = []
        for event_class in type(event).__mro__:
            for handler in list(self._handlers.get(event_class, [])):
                called_count += 1
                try:
                    handler(event)
                except Exception as error:
                    errors.append(error)
        if errors:
            raise ExceptionGroup("event handlers failed", errors)
        return called_count

    def subscriber_count(self, event_type: type) -> int:
        """Handlers registered for exactly event_type."""
        return len(self._handlers.get(event_type, []))


def check_lab_2_6() -> None:
    """Run the same checks as the Lab 2.6 check cells in the notebook."""
    Address, Customer = ValidatedAddress, ValidatedCustomer  # the notebook's names
    print("Exercise 1 — Address / Customer dataclasses with validation")

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
                    Customer(1, "Asha", "asha@example.com")
                    == Customer(1, "A. Rao", "rao@example.com")
                ),
                True,
            ),
            (
                "different id",
                lambda: (
                    Customer(1, "Asha", "asha@example.com")
                    == Customer(2, "Asha", "asha@example.com")
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
    print("Exercise 2 — OrderStatus(StrEnum) with allowed transitions")

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
                lambda: raised_message(
                    lambda: OrderStatus.SHIPPED.transition_to(OrderStatus.PENDING)
                ),
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
    print("Exercise 3 — Permission(Flag)")
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
                lambda: (
                    Permission.WRITE in Permission.EDITOR,
                    Permission.DELETE in Permission.EDITOR,
                ),
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
    print("Exercise 4 — an EventBus")

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


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 2.1", check_lab_2_1),
        ("Lab 2.2", check_lab_2_2),
        ("Lab 2.3", check_lab_2_3),
        ("Lab 2.4", check_lab_2_4),
        ("Lab 2.5", check_lab_2_5),
        ("Lab 2.6", check_lab_2_6),
    ]:
        print(f"\n=== {lab_title} ===")
        check_lab()
