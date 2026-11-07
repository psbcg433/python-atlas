"""Reference solutions for Phase 2 labs.

Run from the repository root:

    uv run python exercises/solutions/phase2_solutions.py
"""

import io
import json
import typing
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
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


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 2.1", check_lab_2_1),
        ("Lab 2.2", check_lab_2_2),
        ("Lab 2.3", check_lab_2_3),
    ]:
        print(f"\n=== {lab_title} ===")
        check_lab()
