"""Phase 2 Project — Inventory Domain Model, closing with 20 predict-the-output questions."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

PROJECT_SETUP_SOURCE = '''
import functools
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum, auto
from typing import Any, Protocol, runtime_checkable

PAISE = Decimal("0.01")


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

MONEY_SOURCE = '''
class CurrencyMismatchError(ValueError):
    """Two Money values in different currencies were combined or compared."""


CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}


@functools.total_ordering
class Money:
    """An immutable amount of money in one currency (Lab 2.4, exercise 1)."""

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
        return self._amount

    @property
    def currency(self) -> str:
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


print(f"{sum([Money('49.99'), Money(100)])=}, {Money('19.99') * 3:symbol}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Project introduction and setup."""
    return [
        md(
            """
            ## Phase 2 Project — Inventory Domain Model

            Model the core of an inventory system for a small chain of stores: products,
            warehouses, stock movements and the rules between them. No database and no web
            framework yet; the goal is a domain model that is correct, readable and easy to test.
            Phase 6 puts a FastAPI app and a real database in front of the same design.

            **Requirements and where each is met**

            | Requirement | Step |
            | --- | --- |
            | `Money` from Unit 2.4 | Step 1 |
            | A frozen, slotted `Product` dataclass | Step 2 |
            | `StockMovement` with a `MovementType` enum | Step 3 |
            | Custom exceptions | Step 4 |
            | A `Warehouse` container class with dunders | Step 5 |
            | An `InventoryRepository` Protocol with an in-memory implementation | Step 6 |
            | An event bus emitting low-stock alerts | Step 7 |
            | An `InventoryService` receiving the repository by injection | Step 8 |
            | A full demo script | Step 9 |
            | Self-check | Step 10 |

            **Design**

            ```mermaid
            flowchart LR
                Demo["demo script"] --> Service["InventoryService"]
                Service -->|"depends on (Protocol)"| Repo["InventoryRepository"]
                Repo -.implemented by.-> Memory["InMemoryInventoryRepository"]
                Service --> Bus["EventBus"]
                Bus --> Alerts["low-stock handlers"]
                Memory --> Warehouse["Warehouse (entity)"]
                Warehouse --> Product["Product (value object)"]
                Product --> Money["Money (value object)"]
                Memory --> Movement["StockMovement + MovementType"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            demo script
                |
                v
            InventoryService ---(Protocol)---> InventoryRepository
                |                                    ^ implemented by
                |                              InMemoryInventoryRepository
                v                                    |
            EventBus --> low-stock handlers          +--> Warehouse (entity) --> Product --> Money
                                                     +--> StockMovement + MovementType
            ```

            </details>

            Value objects (`Money`, `Product`, `StockMovement`) are frozen; the `Warehouse`
            entity changes over time and is equal by its code (Unit 2.6.6). The service is the
            only place that coordinates the others.

            > **Note:** every class this project uses is defined again here, so the project runs
            > on its own after the shared setup cell.
            """
        ),
        code(PROJECT_SETUP_SOURCE),
    ]


def _money_product_cells() -> list[NotebookNode]:
    """Steps 1 and 2."""
    return [
        md(
            """
            ### Step 1 — `Money`

            The immutable `Money` from Lab 2.4 (exercise 1), copied unchanged: amounts rounded
            to the paisa, read-only fields and `__slots__`, value equality and hashing,
            ordering within one currency, `+`, `-`, `*`, `sum()` support and custom format
            specs. If you have not solved the lab yet, this cell is a spoiler for it.
            """
        ),
        code(MONEY_SOURCE),
        md(
            """
            ### Step 2 — a frozen, slotted `Product`

            A product is a **value object**: SKU, name, unit price and the reorder level below
            which stock counts as low. `frozen=True` makes it immutable and hashable,
            `slots=True` drops the per-instance `__dict__` (catalogues can be large), and
            `__post_init__` rejects bad data at the boundary. A price change produces a new
            `Product` with `replace()`.
            """
        ),
        code(
            '''
            SKU_PATTERN = re.compile(r"[A-Z]{2,5}-\\d{2,4}")


            @dataclass(frozen=True, slots=True)
            class Product:
                """A catalogue item. Immutable: change it with dataclasses.replace()."""

                sku: str
                name: str
                unit_price: Money
                reorder_level: int = 5

                def __post_init__(self) -> None:
                    if not SKU_PATTERN.fullmatch(self.sku):
                        raise ValueError(f"invalid SKU {self.sku!r}: expected e.g. 'TEA-500'")
                    if not self.name.strip():
                        raise ValueError("product name is required")
                    if not isinstance(self.unit_price, Money) or self.unit_price.amount <= 0:
                        raise ValueError("unit_price must be a positive Money")
                    if self.reorder_level < 0:
                        raise ValueError("reorder_level must be >= 0")
            '''
        ),
        md(
            """
            What the options buy: no stray attributes, no mutation, hashing (a `set` of
            products), and validation that also runs on `replace()`.
            """
        ),
        code(
            """
            masala_tea = Product("TEA-500", "Masala tea 500 g", Money("240"), reorder_level=10)
            print(masala_tea)
            print(f"{hasattr(masala_tea, '__dict__')=}, {Product.__slots__=}")
            print(raised_message(lambda: set_attribute(masala_tea, "unit_price", Money(1))))
            print(f"{len({masala_tea, Product('TEA-500', 'Masala tea 500 g', Money('240.00'), 10)})=}")
            print(f"{replace(masala_tea, unit_price=Money('255')).unit_price=}")
            print(raised_message(lambda: Product("tea", "Tea", Money(1))))
            print(raised_message(lambda: replace(masala_tea, unit_price=Money(0))))
            """
        ),
    ]


def _movement_exception_cells() -> list[NotebookNode]:
    """Steps 3 and 4."""
    return [
        md(
            """
            ### Step 3 — `StockMovement` with a `MovementType` enum

            Every change to stock is recorded as a movement, never as a bare number, so the
            history explains the current quantity (an audit trail). `MovementType` is a
            `StrEnum`, so it prints and serializes as plain text; each member knows its
            direction. A movement is a frozen, slotted dataclass whose `delta` property gives the
            signed change. Adjustments (stock counts, damage) carry their own sign.
            """
        ),
        code(
            '''
            class MovementType(StrEnum):
                RECEIVED = auto()
                SHIPPED = auto()
                RETURNED = auto()
                ADJUSTED = auto()

                @property
                def direction(self) -> int:
                    """+1 adds stock, -1 removes it, 0 means the quantity carries its own sign."""
                    match self:
                        case MovementType.RECEIVED | MovementType.RETURNED:
                            return 1
                        case MovementType.SHIPPED:
                            return -1
                        case _:
                            return 0


            @dataclass(frozen=True, slots=True)
            class StockMovement:
                warehouse_code: str
                sku: str
                movement_type: MovementType
                quantity: int
                occurred_at: datetime
                note: str = ""

                def __post_init__(self) -> None:
                    if self.movement_type is MovementType.ADJUSTED:
                        if self.quantity == 0:
                            raise ValueError("an adjustment must change the quantity")
                    elif self.quantity <= 0:
                        raise ValueError(f"{self.movement_type} quantity must be positive")

                @property
                def delta(self) -> int:
                    """Signed change in stock."""
                    if self.movement_type is MovementType.ADJUSTED:
                        return self.quantity
                    return self.quantity * self.movement_type.direction
            '''
        ),
        md(
            """
            Movements from each type, and the validation. `occurred_at` is passed explicitly;
            Step 8 injects a clock so the whole project is deterministic.
            """
        ),
        code(
            """
            opening_time = datetime(2026, 11, 7, 9, 0)
            sample_movements = [
                StockMovement("PNQ1", "TEA-500", MovementType.RECEIVED, 40, opening_time),
                StockMovement("PNQ1", "TEA-500", MovementType.SHIPPED, 3, opening_time),
                StockMovement("PNQ1", "TEA-500", MovementType.ADJUSTED, -2, opening_time, "damaged"),
            ]
            print([(str(movement.movement_type), movement.delta) for movement in sample_movements])
            print(f"{sum(movement.delta for movement in sample_movements)=}")
            print(
                raised_message(lambda: StockMovement("PNQ1", "TEA-500", MovementType.SHIPPED, 0, opening_time))
            )
            print(f"{MovementType('shipped') is MovementType.SHIPPED=}, {list(MovementType)=}")
            """
        ),
        md(
            """
            ### Step 4 — custom exceptions

            One base class, `InventoryError`, lets callers catch every domain failure at once;
            each subclass also derives from the matching built-in (`LookupError`, `ValueError`)
            so generic handlers still work (Unit 1.14.5). Each carries an `error_code` and a
            `to_dict()` for the API layer of Phase 6, plus structured attributes instead of
            information buried in the message.
            """
        ),
        code(
            '''
            class InventoryError(Exception):
                """Base class for every inventory rule violation."""

                error_code = "inventory_error"

                def to_dict(self) -> dict[str, str]:
                    return {"error": self.error_code, "message": str(self)}


            class UnknownWarehouseError(InventoryError, LookupError):
                error_code = "unknown_warehouse"

                def __init__(self, warehouse_code: str) -> None:
                    super().__init__(f"no warehouse with code {warehouse_code!r}")
                    self.warehouse_code = warehouse_code


            class UnknownProductError(InventoryError, LookupError):
                error_code = "unknown_product"

                def __init__(self, sku: str, warehouse_code: str) -> None:
                    super().__init__(f"{sku} is not stocked in {warehouse_code}")
                    self.sku, self.warehouse_code = sku, warehouse_code


            class DuplicateProductError(InventoryError, ValueError):
                error_code = "duplicate_product"

                def __init__(self, sku: str, warehouse_code: str) -> None:
                    super().__init__(f"{sku} is already stocked in {warehouse_code}")
                    self.sku, self.warehouse_code = sku, warehouse_code


            class InsufficientStockError(InventoryError):
                error_code = "insufficient_stock"

                def __init__(self, sku: str, available: int, requested: int) -> None:
                    super().__init__(f"not enough {sku}: {available} available, {requested} requested")
                    self.sku, self.available, self.requested = sku, available, requested
            '''
        ),
        md("The hierarchy and one error as the API would report it:"),
        code(
            """
            for error_class in (
                UnknownWarehouseError,
                UnknownProductError,
                DuplicateProductError,
                InsufficientStockError,
            ):
                print(f"{error_class.__name__:<24} {[klass.__name__ for klass in error_class.__mro__[1:-2]]}")
            shortage = InsufficientStockError("TEA-500", 2, 5)
            print(f"{shortage.to_dict()=}, {shortage.available=}")
            """
        ),
    ]


def _warehouse_cells() -> list[NotebookNode]:
    """Step 5."""
    return [
        md(
            """
            ### Step 5 — a `Warehouse` container with dunders

            A warehouse is an **entity**: it is identified by its code while its stock changes,
            so `__eq__` and `__hash__` use the code only. It behaves like a container of
            products (Unit 2.4):

            | Syntax | Method | Meaning |
            | --- | --- | --- |
            | `len(warehouse)` | `__len__` | number of products carried |
            | `sku in warehouse` / `product in warehouse` | `__contains__` | is this product carried? |
            | `warehouse["TEA-500"]` | `__getitem__` | quantity on hand (`UnknownProductError` if not carried) |
            | `for product in warehouse` | `__iter__` | products in SKU order |
            | `bool(warehouse)` | `__bool__` | is **anything** in stock? (not the same as `len > 0`) |
            | `repr(warehouse)` | `__repr__` | code, city, product count |
            | `==`, `hash()` | `__eq__`, `__hash__` | identity by code |

            Stock changes only through `apply(movement)`, which enforces the rules: the product
            must be carried and stock may never go negative.
            """
        ),
        code(
            '''
            class Warehouse:
                """A stock location: the products it carries and their quantities."""

                def __init__(self, code: str, city: str) -> None:
                    self.code, self.city = code, city
                    self._products: dict[str, Product] = {}
                    self._quantities: dict[str, int] = {}

                def __repr__(self) -> str:
                    return f"Warehouse({self.code!r}, {self.city!r}, products={len(self)})"

                def __eq__(self, other: object) -> bool:
                    return self.code == other.code if isinstance(other, Warehouse) else NotImplemented

                def __hash__(self) -> int:
                    return hash(self.code)

                def __len__(self) -> int:
                    return len(self._products)

                def __contains__(self, item: object) -> bool:
                    sku = item.sku if isinstance(item, Product) else item
                    return sku in self._products

                def __getitem__(self, sku: str) -> int:
                    if sku not in self._products:
                        raise UnknownProductError(sku, self.code)
                    return self._quantities[sku]

                def __iter__(self) -> Iterator[Product]:
                    return iter(sorted(self._products.values(), key=lambda product: product.sku))

                def __bool__(self) -> bool:
                    return any(self._quantities.values())

                def product(self, sku: str) -> Product:
                    """The catalogue entry for a carried SKU."""
                    if sku not in self._products:
                        raise UnknownProductError(sku, self.code)
                    return self._products[sku]

                def add_product(self, product: Product) -> None:
                    """Start carrying a product, with zero stock."""
                    if product.sku in self._products:
                        raise DuplicateProductError(product.sku, self.code)
                    self._products[product.sku] = product
                    self._quantities[product.sku] = 0

                def apply(self, movement: StockMovement) -> int:
                    """Apply a movement and return the new quantity."""
                    available = self[movement.sku]
                    if available + movement.delta < 0:
                        raise InsufficientStockError(movement.sku, available, -movement.delta)
                    self._quantities[movement.sku] = available + movement.delta
                    return self._quantities[movement.sku]

                def stock_value(self) -> Money:
                    """Value of everything on hand; start=Money(0) covers an empty warehouse."""
                    return sum((product.unit_price * self[product.sku] for product in self), Money(0))

                def low_stock(self) -> list[Product]:
                    """Products at or below their reorder level."""
                    return [product for product in self if self[product.sku] <= product.reorder_level]
            '''
        ),
        md(
            """
            Exercising every dunder on a small warehouse. Note that a warehouse that carries
            products but has none in stock is falsy, which reads well in `if not warehouse:`.
            """
        ),
        code(
            """
            demo_warehouse = Warehouse("TEST", "Pune")
            demo_warehouse.add_product(masala_tea)
            print(f"{demo_warehouse!r}, {len(demo_warehouse)=}, {bool(demo_warehouse)=}")
            demo_warehouse.apply(StockMovement("TEST", "TEA-500", MovementType.RECEIVED, 12, opening_time))
            print(f"{demo_warehouse['TEA-500']=}, {bool(demo_warehouse)=}")
            print(f"{'TEA-500' in demo_warehouse=}, {masala_tea in demo_warehouse=}")
            print(f"{[product.sku for product in demo_warehouse]=}, {demo_warehouse.stock_value()=}")
            print(f"{demo_warehouse == Warehouse('TEST', 'Mumbai')=}  (entity: same code)")
            print(raised_message(lambda: demo_warehouse["MUG-02"]))
            print(
                raised_message(
                    lambda: demo_warehouse.apply(
                        StockMovement("TEST", "TEA-500", MovementType.SHIPPED, 20, opening_time)
                    )
                )
            )
            print(raised_message(lambda: demo_warehouse.add_product(masala_tea)))
            """
        ),
    ]


def _repository_bus_cells() -> list[NotebookNode]:
    """Steps 6 and 7."""
    return [
        md(
            """
            ### Step 6 — an `InventoryRepository` Protocol and an in-memory implementation

            The service needs somewhere to load and save warehouses and to record movements.
            It depends on a **Protocol** (Unit 2.3.3), not on a concrete class, so the storage
            can change (SQLite in tests, PostgreSQL in Phase 6) without touching the business
            rules (the repository pattern, Unit 2.6.5). `@runtime_checkable` lets the demo
            assert that the in-memory class satisfies it, although it never inherits from it.
            """
        ),
        code(
            '''
            @runtime_checkable
            class InventoryRepository(Protocol):
                def get_warehouse(self, code: str) -> Warehouse: ...
                def save_warehouse(self, warehouse: Warehouse) -> None: ...
                def list_warehouses(self) -> list[Warehouse]: ...
                def record_movement(self, movement: StockMovement) -> None: ...
                def movements(self, *, sku: str | None = None) -> list[StockMovement]: ...


            class InMemoryInventoryRepository:
                """Dict-backed storage for tests and demos."""

                def __init__(self) -> None:
                    self._warehouses: dict[str, Warehouse] = {}
                    self._movements: list[StockMovement] = []

                def get_warehouse(self, code: str) -> Warehouse:
                    try:
                        return self._warehouses[code]
                    except KeyError:
                        raise UnknownWarehouseError(code) from None

                def save_warehouse(self, warehouse: Warehouse) -> None:
                    self._warehouses[warehouse.code] = warehouse

                def list_warehouses(self) -> list[Warehouse]:
                    return sorted(self._warehouses.values(), key=lambda warehouse: warehouse.code)

                def record_movement(self, movement: StockMovement) -> None:
                    self._movements.append(movement)

                def movements(self, *, sku: str | None = None) -> list[StockMovement]:
                    return [movement for movement in self._movements if sku is None or movement.sku == sku]


            print(f"{isinstance(InMemoryInventoryRepository(), InventoryRepository)=}")
            print(f"{InventoryRepository in InMemoryInventoryRepository.__mro__=}  (structural, not inherited)")
            print(raised_message(lambda: InMemoryInventoryRepository().get_warehouse("NOPE")))
            '''
        ),
        md(
            """
            ### Step 7 — an event bus for low-stock alerts

            The service should not know who cares about stock changes (a purchasing e-mail, a
            dashboard, a log). It **publishes events**; handlers subscribe by event class (the
            observer pattern, Unit 2.6.5). Events are frozen dataclasses. This bus is kept
            deliberately small: exact-class dispatch, handlers called in order. Lab 2.6's
            `EventBus` (base-class dispatch, error groups) could replace it unchanged.
            """
        ),
        code(
            '''
            @dataclass(frozen=True)
            class StockChanged:
                warehouse_code: str
                sku: str
                old_quantity: int
                new_quantity: int
                movement_type: MovementType


            @dataclass(frozen=True)
            class LowStockAlert:
                warehouse_code: str
                sku: str
                quantity: int
                reorder_level: int


            class EventBus:
                """Calls the handlers subscribed to the exact class of each published event."""

                def __init__(self) -> None:
                    self._handlers: defaultdict[type, list[Callable[[Any], None]]] = defaultdict(list)

                def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
                    self._handlers[event_type].append(handler)

                def publish(self, event: object) -> int:
                    handlers = self._handlers.get(type(event), [])
                    for handler in handlers:
                        handler(event)
                    return len(handlers)


            trial_bus = EventBus()
            trial_bus.subscribe(
                LowStockAlert, lambda alert: print(f"  ALERT {alert.sku}: {alert.quantity} left")
            )
            print(f"{trial_bus.publish(LowStockAlert('PNQ1', 'TEA-500', 3, 10))=}")
            unwatched_event = StockChanged("PNQ1", "TEA-500", 5, 3, MovementType.SHIPPED)
            print(f"{trial_bus.publish(unwatched_event)=}  (no subscribers)")
            '''
        ),
    ]


def _service_cells() -> list[NotebookNode]:
    """Step 8."""
    return [
        md(
            """
            ### Step 8 — an `InventoryService` with injected dependencies

            The service holds the use cases: open a warehouse, register a product, receive,
            ship, accept returns, adjust after a stock count, and transfer between warehouses.
            Its collaborators arrive through the constructor (**dependency injection**, Unit
            2.6.5): the repository (any object matching the Protocol), the event bus, and a
            `clock`, so tests control time. `_record` is the single place where stock changes:
            it builds the movement, applies it, saves, and publishes `StockChanged`, plus a
            `LowStockAlert` when the quantity **crosses** the reorder level (not on every later
            sale, which would flood the purchasing team).
            """
        ),
        code(
            """
            class InventoryService:
                def __init__(
                    self,
                    repository: InventoryRepository,
                    events: EventBus,
                    clock: Callable[[], datetime] = datetime.now,
                ) -> None:
                    self.repository, self.events, self.clock = repository, events, clock

                def open_warehouse(self, code: str, city: str) -> Warehouse:
                    warehouse = Warehouse(code, city)
                    self.repository.save_warehouse(warehouse)
                    return warehouse

                def register_product(self, warehouse_code: str, product: Product) -> None:
                    warehouse = self.repository.get_warehouse(warehouse_code)
                    warehouse.add_product(product)
                    self.repository.save_warehouse(warehouse)

                def receive(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
                    return self._record(warehouse_code, sku, MovementType.RECEIVED, quantity, note)

                def ship(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
                    return self._record(warehouse_code, sku, MovementType.SHIPPED, quantity, note)

                def accept_return(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
                    return self._record(warehouse_code, sku, MovementType.RETURNED, quantity, note)

                def adjust(self, warehouse_code: str, sku: str, change: int, note: str) -> int:
                    return self._record(warehouse_code, sku, MovementType.ADJUSTED, change, note)
            """
        ),
        md(
            """
            The rest of the class: transfers, reporting, and the shared `_record` step. A
            transfer checks **both** sides before moving anything, so a failure leaves stock
            untouched; the destination starts carrying the product if it did not already.
            """
        ),
        code(
            """
            class InventoryService(InventoryService):  # the second half of the class
                def transfer(self, from_code: str, to_code: str, sku: str, quantity: int) -> None:
                    source = self.repository.get_warehouse(from_code)
                    destination = self.repository.get_warehouse(to_code)
                    if source[sku] < quantity:
                        raise InsufficientStockError(sku, source[sku], quantity)
                    if sku not in destination:
                        self.register_product(to_code, source.product(sku))
                    self.ship(from_code, sku, quantity, note=f"transfer to {to_code}")
                    self.receive(to_code, sku, quantity, note=f"transfer from {from_code}")

                def total_value(self) -> Money:
                    return sum(
                        (warehouse.stock_value() for warehouse in self.repository.list_warehouses()), Money(0)
                    )

                def stock_report(self, warehouse_code: str) -> list[str]:
                    warehouse = self.repository.get_warehouse(warehouse_code)
                    lines = [
                        f"{warehouse.code} ({warehouse.city})",
                        f"{'SKU':<9}{'Product':<20}{'Qty':>5}{'Value (INR)':>14}",
                    ]
                    for product in warehouse:
                        flag = "  LOW" if product in warehouse.low_stock() else ""
                        value = product.unit_price * warehouse[product.sku]
                        quantity = warehouse[product.sku]
                        lines.append(
                            f"{product.sku:<9}{product.name[:19]:<20}{quantity:>5}{value.amount:>14,.2f}{flag}"
                        )
                    lines.append(f"{'Total':<34}{warehouse.stock_value().amount:>14,.2f}")
                    return lines

                def _record(
                    self, warehouse_code: str, sku: str, movement_type: MovementType, quantity: int, note: str
                ) -> int:
                    warehouse = self.repository.get_warehouse(warehouse_code)
                    old_quantity = warehouse[sku]
                    movement = StockMovement(warehouse_code, sku, movement_type, quantity, self.clock(), note)
                    new_quantity = warehouse.apply(movement)
                    self.repository.record_movement(movement)
                    self.repository.save_warehouse(warehouse)
                    self.events.publish(
                        StockChanged(warehouse_code, sku, old_quantity, new_quantity, movement_type)
                    )
                    reorder_level = warehouse.product(sku).reorder_level
                    if old_quantity > reorder_level >= new_quantity:
                        self.events.publish(LowStockAlert(warehouse_code, sku, new_quantity, reorder_level))
                    return new_quantity
            """
        ),
    ]


def _demo_cells() -> list[NotebookNode]:
    """Step 9."""
    return [
        md(
            """
            ### Step 9 — the full demo script

            Wire everything together: a fake clock that ticks one minute per movement, the
            in-memory repository, the bus with two subscribers (an alert collector standing in
            for "e-mail purchasing", and a counter of stock changes), and the service.
            """
        ),
        code(
            '''
            def make_clock(start: datetime, step: timedelta = timedelta(minutes=1)) -> Callable[[], datetime]:
                """A deterministic clock: start, start + step, start + 2 * step, ..."""
                readings = iter(start + step * tick for tick in range(1_000_000))
                return lambda: next(readings)


            repository = InMemoryInventoryRepository()
            event_bus = EventBus()
            alerts: list[LowStockAlert] = []
            change_counts: defaultdict[MovementType, int] = defaultdict(int)
            event_bus.subscribe(LowStockAlert, alerts.append)
            event_bus.subscribe(
                StockChanged,
                lambda event: change_counts.__setitem__(
                    event.movement_type, change_counts[event.movement_type] + 1
                ),
            )
            service = InventoryService(repository, event_bus, clock=make_clock(datetime(2026, 11, 7, 9, 0)))

            catalogue = [
                Product("TEA-500", "Masala tea 500 g", Money("240"), reorder_level=10),
                Product("MUG-02", "Steel mug", Money("199"), reorder_level=4),
                Product("JAR-10", "Glass jar 1 L", Money("149.50"), reorder_level=6),
            ]
            for warehouse_code, city in [("PNQ1", "Pune"), ("BLR2", "Bengaluru")]:
                service.open_warehouse(warehouse_code, city)
            for product in catalogue:
                service.register_product("PNQ1", product)
            print(repository.list_warehouses())
            '''
        ),
        md(
            """
            A day of business at the Pune warehouse: a delivery arrives, orders ship, one
            customer returns a mug, a stock count finds two broken jars. Shipping the mugs below
            their reorder level of 4 raises exactly one alert.
            """
        ),
        code(
            """
            service.receive("PNQ1", "TEA-500", 40, note="PO-1001")
            service.receive("PNQ1", "MUG-02", 12, note="PO-1001")
            service.receive("PNQ1", "JAR-10", 20, note="PO-1002")
            for sku, quantity in [("TEA-500", 5), ("MUG-02", 6), ("MUG-02", 3), ("TEA-500", 8), ("JAR-10", 2)]:
                service.ship("PNQ1", sku, quantity, note="customer order")
            service.accept_return("PNQ1", "MUG-02", 1, note="wrong colour")
            service.adjust("PNQ1", "JAR-10", -2, note="stock count: 2 broken")
            print(f"{alerts=}")
            print(f"{dict(change_counts)=}")
            """
        ),
        md(
            """
            Failures are domain exceptions with structured data. One `except InventoryError`
            catches them all, and `to_dict()` is what an API would return. None of the failed
            calls changed any stock.
            """
        ),
        code(
            """
            failing_operations = {
                "ship too many mugs": lambda: service.ship("PNQ1", "MUG-02", 50),
                "unknown product": lambda: service.receive("PNQ1", "PEN-01", 5),
                "unknown warehouse": lambda: service.receive("DEL9", "TEA-500", 5),
                "register twice": lambda: service.register_product("PNQ1", catalogue[0]),
            }
            for description, operation in failing_operations.items():
                try:
                    operation()
                except InventoryError as error:
                    print(f"{description:<18} -> {error.to_dict()}")
            print(f"{repository.get_warehouse('PNQ1')['MUG-02']=}  (unchanged by the failures)")
            """
        ),
        md(
            """
            A transfer to Bengaluru: the destination starts carrying the product, and the
            Pune tea stock crosses its reorder level of 10, so a second alert fires. A
            transfer that is too large fails before anything moves.
            """
        ),
        code(
            """
            service.transfer("PNQ1", "BLR2", "TEA-500", 20)
            pune, bengaluru = repository.get_warehouse("PNQ1"), repository.get_warehouse("BLR2")
            print(f"{pune['TEA-500']=}, {bengaluru['TEA-500']=}")
            print(f"{alerts[-1]=}")
            print(raised_message(lambda: service.transfer("PNQ1", "BLR2", "JAR-10", 100)))
            print(f"{'JAR-10' in repository.get_warehouse('BLR2')=}  (nothing registered or moved)")
            """
        ),
        md(
            """
            The reports and the audit trail. Every line of the report comes from the dunders
            (`for product in warehouse`, `warehouse[sku]`), `Money` arithmetic and
            `Money.__format__`; the history replays every movement of one SKU in order with
            its timestamp.
            """
        ),
        code(
            """
            for warehouse in repository.list_warehouses():
                print("\\n".join(service.stock_report(warehouse.code)))
                print()
            print(f"Total stock value: {service.total_value():symbol}")
            low_stock_skus = [product.sku for product in repository.get_warehouse("PNQ1").low_stock()]
            print(f"Low stock in PNQ1: {low_stock_skus}")
            """
        ),
        md("The movement history for the mugs, and a check that it explains the current quantity:"),
        code(
            """
            mug_history = repository.movements(sku="MUG-02")
            for movement in mug_history:
                when, kind = f"{movement.occurred_at:%H:%M}", f"{movement.movement_type:<9}"
                print(f"{when}  {kind} {movement.delta:+4d}  {movement.note}")
            mug_total = sum(movement.delta for movement in mug_history)
            print(f"{mug_total=}, {repository.get_warehouse('PNQ1')['MUG-02']=}")
            """
        ),
    ]


def _self_check_cells() -> list[NotebookNode]:
    """Step 10."""
    return [
        md(
            """
            ### Step 10 — self-check

            The project's own checks: each builds a **fresh** service, so they do not depend on
            the demo above. All should pass.
            """
        ),
        code(
            '''
            def fresh_service() -> tuple[InventoryService, InMemoryInventoryRepository, list[object]]:
                """A service with one warehouse, one product and a recording bus."""
                fresh_repository, fresh_bus, published = InMemoryInventoryRepository(), EventBus(), []
                fresh_bus.subscribe(LowStockAlert, published.append)
                fresh_bus.subscribe(StockChanged, published.append)
                fresh = InventoryService(fresh_repository, fresh_bus, clock=make_clock(datetime(2026, 1, 1)))
                fresh.open_warehouse("W1", "Pune")
                fresh.register_product("W1", Product("TEA-500", "Tea", Money("100"), reorder_level=3))
                return fresh, fresh_repository, published


            def alert_only_on_crossing() -> int:
                fresh, _, published = fresh_service()
                fresh.receive("W1", "TEA-500", 10)
                for _ in range(5):
                    fresh.ship("W1", "TEA-500", 2)  # 8, 6, 4, 2 (crosses 3), 0
                return sum(isinstance(event, LowStockAlert) for event in published)


            def failed_transfer_moves_nothing() -> tuple[int, bool, int]:
                fresh, fresh_repository, _ = fresh_service()
                fresh.open_warehouse("W2", "Mumbai")
                fresh.receive("W1", "TEA-500", 5)
                try:
                    fresh.transfer("W1", "W2", "TEA-500", 9)
                except InsufficientStockError:
                    pass
                return (
                    fresh_repository.get_warehouse("W1")["TEA-500"],
                    "TEA-500" in fresh_repository.get_warehouse("W2"),
                    len(fresh_repository.movements()),
                )


            def history_matches_stock() -> bool:
                fresh, fresh_repository, _ = fresh_service()
                fresh.receive("W1", "TEA-500", 7)
                fresh.ship("W1", "TEA-500", 4)
                fresh.accept_return("W1", "TEA-500", 1)
                fresh.adjust("W1", "TEA-500", -1, "count")
                return (
                    sum(movement.delta for movement in fresh_repository.movements())
                    == fresh_repository.get_warehouse("W1")["TEA-500"]
                )
            '''
        ),
        md("Run the self-check:"),
        code(
            """
            run_checks(
                [
                    ("Money sum", lambda: sum([Money("0.10")] * 3), Money("0.30")),
                    (
                        "Product frozen and slotted",
                        lambda: (
                            raised_error_name(lambda: set_attribute(catalogue[0], "name", "x")),
                            hasattr(catalogue[0], "__dict__"),
                        ),
                        ("FrozenInstanceError", False),
                    ),
                    (
                        "repository satisfies the Protocol",
                        lambda: isinstance(InMemoryInventoryRepository(), InventoryRepository),
                        True,
                    ),
                    (
                        "receive then ship",
                        lambda: (
                            lambda fresh: (fresh.receive("W1", "TEA-500", 10), fresh.ship("W1", "TEA-500", 4))
                        )(fresh_service()[0]),
                        (10, 6),
                    ),
                    (
                        "cannot oversell",
                        lambda: raised_error_name(lambda: fresh_service()[0].ship("W1", "TEA-500", 1)),
                        "InsufficientStockError",
                    ),
                    (
                        "errors share a base",
                        lambda: all(
                            issubclass(error, InventoryError)
                            for error in (
                                UnknownProductError,
                                UnknownWarehouseError,
                                DuplicateProductError,
                                InsufficientStockError,
                            )
                        ),
                        True,
                    ),
                    (
                        "lookup errors are LookupErrors",
                        lambda: issubclass(UnknownProductError, LookupError),
                        True,
                    ),
                    ("alert only on crossing", alert_only_on_crossing, 1),
                    ("failed transfer moves nothing", failed_transfer_moves_nothing, (5, False, 1)),
                    ("history explains stock", history_matches_stock, True),
                    (
                        "warehouse equality by code",
                        lambda: Warehouse("W1", "Pune") == Warehouse("W1", "Goa"),
                        True,
                    ),
                    (
                        "demo totals",
                        lambda: (
                            repository.get_warehouse("PNQ1")["TEA-500"],
                            repository.get_warehouse("PNQ1")["MUG-02"],
                            len(alerts),
                        ),
                        (7, 4, 2),
                    ),
                ]
            )
            """
        ),
        md(
            """
            **Ideas to extend it** (good practice before Phase 6): replace `EventBus` with the
            Lab 2.6 version and subscribe to the `object` class to log everything; add a
            `Reservation` value object so orders hold stock before shipping; store
            `StockMovement`s in SQLite behind a second repository class that satisfies the same
            Protocol (the service code does not change); add `Warehouse.__format__` with a
            `"report"` spec.
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    # (unit, snippet, answer, proof); proof is the snippet unless given separately
    (
        "2.1",
        """
        class Counter:
            count = 0

            def __init__(self):
                self.count += 1

        first, second = Counter(), Counter()
        print(first.count, second.count, Counter.count)
        """,
        """
        `1 1 0`. `self.count += 1` reads `self.count` (found on the **class**: 0), adds 1,
        then **assigns** to `self.count`, which creates an instance attribute. Each instance
        gets its own `1`; the class attribute never changes.
        """,
        """
        class Counter:
            count = 0

            def __init__(self) -> None:
                self.count += 1


        first, second = Counter(), Counter()
        print(first.count, second.count, Counter.count)
        """,
    ),
    (
        "2.1",
        """
        class Cart:
            items = []

            def add(self, item):
                self.items.append(item)

        first_cart, second_cart = Cart(), Cart()
        first_cart.add("tea")
        print(second_cart.items, first_cart.items is second_cart.items)
        """,
        """
        `['tea'] True`. `self.items.append` **mutates** the one list stored on the class
        (no assignment, so no instance attribute is created). Every cart shares it. Create
        the list in `__init__` instead (Unit 2.1.3).
        """,
        """
        class Cart:
            items: list[str] = []  # the shared mutable class attribute trap

            def add(self, item: str) -> None:
                self.items.append(item)


        first_cart, second_cart = Cart(), Cart()
        first_cart.add("tea")
        print(second_cart.items, first_cart.items is second_cart.items)
        """,
    ),
    (
        "2.1",
        """
        class Vault:
            def __init__(self):
                self.__pin = 1234

        vault = Vault()
        print(hasattr(vault, "__pin"), vault._Vault__pin)
        """,
        """
        `False 1234`. Inside a class body, `__pin` is **name-mangled** to `_Vault__pin`.
        It is a guard against accidental clashes in subclasses, not privacy: the mangled name
        is still reachable (Unit 2.1.7).
        """,
        """
        class Vault:
            def __init__(self) -> None:
                self.__pin = 1234


        vault = Vault()
        print(hasattr(vault, "__pin"), vault._Vault__pin)
        """,
    ),
    (
        "2.2",
        """
        class A:
            def hello(self): return "A"
        class B(A):
            def hello(self): return "B" + super().hello()
        class C(A):
            def hello(self): return "C" + super().hello()
        class D(B, C):
            def hello(self): return "D" + super().hello()

        print(D().hello())
        """,
        """
        `DBCA`. `super()` means "the next class in the **instance's** MRO", which is
        `D, B, C, A, object`. So `B`'s `super()` call reaches `C`, not `A` (Unit 2.2.3).
        """,
        """
        class A:
            def hello(self) -> str:
                return "A"


        class B(A):
            def hello(self) -> str:
                return "B" + super().hello()


        class C(A):
            def hello(self) -> str:
                return "C" + super().hello()


        class D(B, C):
            def hello(self) -> str:
                return "D" + super().hello()


        print(D().hello())
        """,
    ),
    (
        "2.2",
        """
        class Shipment: pass
        class Express(Shipment): pass

        parcel = Express()
        print(isinstance(parcel, Shipment), type(parcel) == Shipment, issubclass(Express, object))
        """,
        """
        `True False True`. `isinstance` respects inheritance; `type(x) ==` compares the exact
        class and breaks substitutability (Liskov, Unit 2.2.5). Every class ultimately
        inherits from `object`.
        """,
        """
        class Shipment:
            pass


        class Express(Shipment):
            pass


        parcel = Express()
        exact_type_match = type(parcel) == Shipment  # noqa: E721 (the point of the question)
        print(isinstance(parcel, Shipment), exact_type_match, issubclass(Express, object))
        """,
    ),
    (
        "2.2",
        """
        class Base:
            def __init__(self):
                self.created = True

        class Child(Base):
            def __init__(self):
                self.name = "child"

        print(hasattr(Child(), "created"))
        """,
        """
        `False`. Defining `__init__` in `Child` **replaces** `Base.__init__`; Python never
        calls the parent initializer automatically. Call `super().__init__()` (Unit 2.2.1).
        """,
        """
        class Base:
            def __init__(self) -> None:
                self.created = True


        class Child(Base):
            def __init__(self) -> None:
                self.name = "child"


        print(hasattr(Child(), "created"))
        """,
    ),
    (
        "2.3",
        """
        from abc import ABC, abstractmethod

        class Repository(ABC):
            @abstractmethod
            def get(self, key): ...

        class Partial(Repository):
            pass

        try:
            Partial()
        except TypeError:
            print("TypeError")
        print(Repository.__abstractmethods__)
        """,
        """
        `TypeError`, then `frozenset({'get'})`. Defining `Partial` is fine; **instantiating**
        a class that still has abstract methods fails. `ABCMeta` records them in
        `__abstractmethods__` (Unit 2.3.1).
        """,
        """
        from abc import ABC, abstractmethod


        class Repository(ABC):
            @abstractmethod
            def get(self, key: str) -> object: ...


        class Partial(Repository):
            pass


        try:
            Partial()
        except TypeError:
            print("TypeError")
        print(Repository.__abstractmethods__)
        """,
    ),
    (
        "2.3",
        """
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class Closer(Protocol):
            def close(self) -> None: ...

        class Door:
            close = "not a method"

        print(isinstance(Door(), Closer))
        """,
        """
        `True`. A runtime-checkable Protocol only checks that the **names** exist, not their
        types or signatures (Unit 2.3.3). A type checker would reject `Door` as a `Closer`.
        """,
        """
        from typing import Protocol, runtime_checkable


        @runtime_checkable
        class Closer(Protocol):
            def close(self) -> None: ...


        class Door:
            close = "not a method"


        print(isinstance(Door(), Closer))
        """,
    ),
    (
        "2.3",
        """
        from collections.abc import Sized

        class Box:
            def __len__(self):
                return 0

        print(isinstance(Box(), Sized), bool(Box()))
        """,
        """
        `True False`. `Sized.__subclasshook__` accepts any class with `__len__`, no
        inheritance needed (Unit 2.3.2), and `bool()` falls back to `__len__`, so an empty box
        is falsy (Unit 2.4.5).
        """,
        """
        from collections.abc import Sized


        class Box:
            def __len__(self) -> int:
                return 0


        print(isinstance(Box(), Sized), bool(Box()))
        """,
    ),
    (
        "2.4",
        """
        class Points:
            def __init__(self, value):
                self.value = value

            def __add__(self, other):
                return Points(self.value + other.value)

        print(sum([Points(1), Points(2)]).value)
        """,
        """
        `TypeError: unsupported operand type(s) for +: 'int' and 'Points'`. `sum()` starts
        from `0`, so the first step is `0 + Points(1)`: `int.__add__` declines and `Points`
        has no `__radd__` (Unit 2.4.8).
        """,
        """
        class Points:
            def __init__(self, value: int) -> None:
                self.value = value

            def __add__(self, other: Points) -> Points:
                return Points(self.value + other.value)


        try:
            print(sum([Points(1), Points(2)]).value)  # type: ignore[arg-type]
        except TypeError as error:
            print(f"TypeError: {error}")
        """,
    ),
    (
        "2.4",
        """
        class Tag:
            def __init__(self, name):
                self.name = name

            def __eq__(self, other):
                if not isinstance(other, Tag):
                    return NotImplemented
                return self.name == other.name

        print(Tag("a") == Tag("a"), Tag("a") == "a", Tag("a") != "a")
        """,
        """
        `True False True`. Against a `str`, both sides return `NotImplemented`, so `==` falls
        back to identity (`False`) and `!=` to non-identity (`True`); no exception (Unit
        2.4.3).
        """,
        """
        class Tag:
            def __init__(self, name: str) -> None:
                self.name = name

            def __eq__(self, other: object) -> bool:
                if not isinstance(other, Tag):
                    return NotImplemented
                return self.name == other.name


        print(Tag("a") == Tag("a"), Tag("a") == "a", Tag("a") != "a")
        """,
    ),
    (
        "2.4",
        """
        class Queue:
            def __len__(self):
                return 3

            def __bool__(self):
                return False

        queue = Queue()
        print(len(queue), bool(queue), "yes" if queue else "no")
        """,
        """
        `3 False no`. `__bool__` takes precedence over `__len__` for truth tests (Unit 2.4.5).
        """,
        """
        class Queue:
            def __len__(self) -> int:
                return 3

            def __bool__(self) -> bool:
                return False


        queue = Queue()
        print(len(queue), bool(queue), "yes" if queue else "no")
        """,
    ),
    (
        "2.4",
        """
        class Echo:
            def __getitem__(self, index):
                return index

        echo = Echo()
        print(echo[2], echo[1:3], echo[::2])
        """,
        """
        `2 slice(1, 3, None) slice(None, None, 2)`. Slicing syntax builds a `slice` object
        and passes it to `__getitem__`; your class decides what to do with it (Unit 2.4.6).
        """,
        """
        class Echo:
            def __getitem__(self, index: int | slice) -> int | slice:
                return index


        echo = Echo()
        print(echo[2], echo[1:3], echo[::2])
        """,
    ),
    (
        "2.5",
        """
        class Item:
            @property
            def price(self):
                return 100

        item = Item()
        item.__dict__["price"] = 5
        print(item.price)
        """,
        """
        `100`. A property is a **data** descriptor, which wins over the instance `__dict__`
        in attribute lookup (Unit 2.5.1).
        """,
        """
        class Item:
            @property
            def price(self) -> int:
                return 100


        item = Item()
        item.__dict__["price"] = 5
        print(item.price)
        """,
    ),
    (
        "2.5",
        """
        class Item:
            def price(self):
                return 100

        item = Item()
        item.price = 5
        print(item.price, Item().price())
        """,
        """
        `5 100`. A function is a **non-data** descriptor, so the instance attribute shadows
        the method on that one instance; other instances still see the method (Unit 2.5.4).
        """,
        """
        class Item:
            def price(self) -> int:
                return 100


        item = Item()
        item.price = 5  # type: ignore[method-assign]
        print(item.price, Item().price())
        """,
    ),
    (
        "2.5",
        """
        class Defaults:
            colour = "red"

            def __getattr__(self, name):
                return f"default-{name}"

        defaults = Defaults()
        print(defaults.colour, defaults.size)
        """,
        """
        `red default-size`. `__getattr__` runs only when normal lookup **fails**; `colour` is
        found on the class first (Unit 2.5.2).
        """,
        """
        class Defaults:
            colour = "red"

            def __getattr__(self, name: str) -> str:
                return f"default-{name}"


        defaults = Defaults()
        print(defaults.colour, defaults.size)
        """,
    ),
    (
        "2.5",
        """
        class Base:
            registry = []

            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__(**kwargs)
                Base.registry.append(cls.__name__)

        class A(Base): pass
        class B(A): pass

        print(Base.registry)
        """,
        """
        `['A', 'B']`. `__init_subclass__` runs for **every** descendant, including
        grandchildren, but not for `Base` itself (Unit 2.5.8).
        """,
        """
        class Base:
            registry: list[str] = []

            def __init_subclass__(cls, **kwargs: object) -> None:
                super().__init_subclass__(**kwargs)
                Base.registry.append(cls.__name__)


        class A(Base):
            pass


        class B(A):
            pass


        print(Base.registry)
        """,
    ),
    (
        "2.6",
        """
        from dataclasses import dataclass, field

        @dataclass(order=True)
        class Task:
            priority: int
            name: str = field(compare=False)

        tasks = [Task(2, "b"), Task(1, "z"), Task(2, "a")]
        print([task.name for task in sorted(tasks)], Task(1, "x") == Task(1, "y"))
        """,
        """
        `['z', 'b', 'a'] True`. Only `priority` is compared. The two priority-2 tasks are
        equal for sorting, and `sorted` is **stable**, so `b` stays before `a` (Unit 2.6.1).
        """,
        """
        from dataclasses import dataclass, field


        @dataclass(order=True)
        class Task:
            priority: int
            name: str = field(compare=False)


        tasks = [Task(2, "b"), Task(1, "z"), Task(2, "a")]
        print([task.name for task in sorted(tasks)], Task(1, "x") == Task(1, "y"))
        """,
    ),
    (
        "2.6",
        """
        from dataclasses import dataclass

        @dataclass
        class Point:
            x: int

        @dataclass(frozen=True)
        class FrozenPoint:
            x: int

        print(Point.__hash__ is None, hash(FrozenPoint(1)) == hash(FrozenPoint(1)))
        """,
        """
        `True True`. A plain dataclass generates `__eq__`, which switches hashing off (Unit
        2.4.3); `frozen=True` makes the fields immutable, so a `__hash__` is generated.
        """,
        """
        from dataclasses import dataclass


        @dataclass
        class Point:
            x: int


        @dataclass(frozen=True)
        class FrozenPoint:
            x: int


        print(Point.__hash__ is None, hash(FrozenPoint(1)) == hash(FrozenPoint(1)))
        """,
    ),
    (
        "2.6",
        """
        from enum import StrEnum, auto

        class Env(StrEnum):
            DEV = auto()
            PROD = auto()

        print(Env.PROD == "prod", f"{Env.DEV}", Env("prod") is Env.PROD)
        """,
        """
        `True dev True`. `auto()` in a `StrEnum` gives the lower-cased name; members are
        real strings, format as their value, and `Env("prod")` looks up the existing
        singleton (Unit 2.6.4).
        """,
        """
        from enum import StrEnum, auto


        class Env(StrEnum):
            DEV = auto()
            PROD = auto()


        print(Env.PROD == "prod", f"{Env.DEV}", Env("prod") is Env.PROD)
        """,
    ),
]


def _question_cells() -> list[NotebookNode]:
    """The 20 predict-the-output questions covering Phase 2."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage_rows = "\n".join(
        f"            | {unit} | {count} |" for unit, count in unit_counts.items()
    )
    cells = [
        md(
            f"""
            ### Phase 2 review — 20 predict-the-output questions

            Twenty short snippets, at least three from every unit of the phase. For each one,
            decide what it prints **before** opening the answer, then run the proof cell. If a
            question surprises you, go back to the unit it names. Snippets leave out type hints
            to stay short; the proof cells add them.

            | Unit | Questions |
            | --- | --- |
{coverage_rows}
            """
        )
    ]
    for question_number, (unit, snippet, answer, proof) in enumerate(QUESTIONS, start=1):
        cells.append(md(f"#### Question {question_number} — Unit {unit}"))
        cells.extend(predict_cells(snippet=snippet, answer=answer, proof=proof or snippet))
    return cells


def _closing_cells() -> list[NotebookNode]:
    """Phase 2 closing."""
    return [
        md(
            """
            ### Phase 2 complete

            You can now design classes that behave like built-ins (dunders), choose between
            inheritance, composition, ABCs and Protocols, explain how attribute lookup,
            descriptors and metaclasses work (and so how Pydantic, SQLAlchemy and dataclasses
            work), and model a domain with dataclasses, enums, value objects, entities, a
            repository, dependency injection and events.

            **Next: Phase 3 — Python Internals: Memory, Bytecode and Imports.** Reference
            counting and the garbage collector behind the objects you have been creating, the
            bytecode that `BINARY_OP` and `LOAD_ATTR` belong to, and the import system that
            makes a module-level object a singleton.
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 2 Project and the closing review."""
    return [
        *_overview_cells(),
        *_money_product_cells(),
        *_movement_exception_cells(),
        *_warehouse_cells(),
        *_repository_bus_cells(),
        *_service_cells(),
        *_demo_cells(),
        *_self_check_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
