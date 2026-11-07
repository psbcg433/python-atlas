"""Unit 2.1 — Classes and Instances (with Lab 2.1)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import dis
import functools
import inspect
import sys
import types
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, NamedTuple, Self

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


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 2.1 — Classes and Instances

            **Objectives**

            - Decide when a class is the right tool, and when a function, a module or a
              dataclass is better.
            - Explain what the `class` statement does at run time, down to the `type(...)` call.
            - Trace object creation through `__new__` and `__init__`, and inspect instances with
              `vars()` and `__class__`.
            - Predict attribute lookup (instance → class → bases) and avoid the shared mutable
              class-attribute trap.
            - Choose between instance methods, `@classmethod` and `@staticmethod`, and write
              subclass-aware alternative constructors.
            - Use `@property` for computed, read-only and validated attributes.
            - Use Python's privacy conventions and compare them with JavaScript `#private`.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `class Cart { constructor(items) { … } }` | `class Cart:` + `def __init__(self, items):` | Construction is two steps (`__new__` allocates, `__init__` fills in) |
            | `this` (set by the call site) | `self` (an explicit first parameter) | `self` is bound when you look the method up, so it is never "lost" |
            | `obj.method.bind(obj)` | `obj.method` | A bound method already remembers its instance |
            | Class field `items = []` (one array **per instance**) | Class attribute `items = []` (one list **shared** by all instances) | The most common Python class bug, see 2.1.4 |
            | `static create() {}` | `@classmethod` / `@staticmethod` | `@classmethod` receives the class, so it builds the right subclass |
            | `get total() {}` / `set total(v) {}` | `@property` / `@total.setter` | Same idea; Python has a deleter too |
            | `#balance` (engine-enforced) / TS `private` (compile-time) | `_balance` (convention) / `__balance` (name mangling) | Nothing in Python is truly private |
            | `Counter.prototype.reset = …` | `Counter.reset = reset` | Python classes are mutable objects too; instances see the change |
            | `class` expression, `Object.create` | `type(name, bases, namespace)` | A class is built at run time by calling its metaclass |

            The next cell is this unit's setup. `raised_message(thunk)` is new: like
            `raised_error_name` from Phase 1, but it also returns the error message.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _why_classes_cells() -> list[NotebookNode]:
    """2.1.1 Why classes."""
    return [
        md(
            """
            ### 2.1.1 Why classes

            A class **bundles state with the behaviour that keeps that state valid**. Without a
            class you can still keep data in a `dict` and write functions that work on it, but
            nothing ties the rules to the data: any code can put the dict into an invalid state.

            The next cell keeps stock levels in a plain dict. `ship_stock` refuses to go below
            zero, but the last assignment ignores the rule completely.
            """
        ),
        code(
            '''
            def make_stock_item(sku: str, quantity: int) -> dict[str, Any]:
                """Create a stock record as a plain dict."""
                return {"sku": sku, "quantity": quantity}


            def ship_stock(stock_item: dict[str, Any], units: int) -> None:
                """Ship units, refusing to go below zero."""
                if units > stock_item["quantity"]:
                    raise ValueError(f"only {stock_item['quantity']} left")
                stock_item["quantity"] -= units


            soap_stock = make_stock_item("SOAP", 10)
            ship_stock(soap_stock, 3)
            soap_stock["quantity"] = -50  # nothing stops this: the rule lives in ship_stock only
            print(f"{soap_stock=}")
            '''
        ),
        md(
            """
            The same idea as a class. The quantity can only change through `receive()` and
            `ship()`, and the read-only `quantity` property (2.1.6) refuses direct assignment.
            Notice the `AttributeError` at the end: the invalid state is now impossible from
            outside.
            """
        ),
        code(
            '''
            class StockItem:
                """Stock for one SKU; quantity changes only through receive() and ship()."""

                def __init__(self, sku: str, quantity: int) -> None:
                    self.sku = sku
                    self._quantity = quantity

                @property
                def quantity(self) -> int:
                    """Units on hand (read-only from outside)."""
                    return self._quantity

                def receive(self, units: int) -> None:
                    """Add units from a delivery."""
                    self._quantity += units

                def ship(self, units: int) -> None:
                    """Remove units, refusing to go below zero."""
                    if units > self._quantity:
                        raise ValueError(f"only {self._quantity} left")
                    self._quantity -= units


            soap = StockItem("SOAP", 10)
            soap.ship(3)
            soap.receive(5)
            print(f"{soap.quantity=}")
            print(raised_message(lambda: setattr(soap, "quantity", -50)))
            '''
        ),
        md(
            """
            A class is not always the answer. Python has three lighter tools, and idiomatic code
            uses them first:

            | You need | Best tool | Why |
            | --- | --- | --- |
            | A stateless calculation | a **function** | Nothing to remember between calls (`add_gst(amount)`) |
            | A group of related functions and constants, one copy | a **module** | A module is already a singleton namespace (`import settings`) |
            | A record of data with little behaviour | a **dataclass** or `NamedTuple` (2.6, 1.5.6) | `__init__`, `__repr__`, `__eq__` are generated for you |
            | State plus rules that must always hold (invariants) | a **class** | Methods guard the state |
            | Several interchangeable implementations | a **class** + ABC / Protocol (2.3) | Callers depend on the shared interface |

            A common smell is a class with only `__init__` and one method: it is a function in
            disguise. Both versions below compute the same thing; the function is shorter and
            easier to test.
            """
        ),
        code(
            '''
            class GstCalculator:
                """A class that only wraps one function (a smell)."""

                def __init__(self, rate_percent: Decimal) -> None:
                    self.rate_percent = rate_percent

                def calculate(self, amount: Decimal) -> Decimal:
                    """Return amount plus GST, rounded to the paisa."""
                    return (amount * (1 + self.rate_percent / 100)).quantize(PAISE, ROUND_HALF_UP)


            def add_gst(amount: Decimal, rate_percent: Decimal = Decimal("18")) -> Decimal:
                """The same thing as one function."""
                return (amount * (1 + rate_percent / 100)).quantize(PAISE, ROUND_HALF_UP)


            print(f"{GstCalculator(Decimal('18')).calculate(Decimal('499'))=}")
            print(f"{add_gst(Decimal('499'))=}")
            '''
        ),
        md(
            """
            A **module** is an object too: `import math` gives you a `module` instance whose
            attributes are the functions and constants defined in the file. That is why Python
            needs no "static utility class" (`class MathUtils { static … }` in Java). The cell
            builds a module object by hand to show it is just a namespace.
            """
        ),
        code(
            """
            import math

            print(f"{type(math).__name__=}, {math.tau=:.4f}")
            settings = types.ModuleType("settings")  # what `import settings` would give you
            settings.DEBUG = False
            settings.PAGE_SIZE = 20
            print(f"{type(settings).__name__=}, {settings.PAGE_SIZE=}")
            """
        ),
        md(
            """
            For plain records, a **dataclass** (Unit 2.6) writes the boring methods for you.
            Here `@dataclass` generated `__init__`, a readable `__repr__` and a value-based
            `__eq__` from three annotated lines.
            """
        ),
        code(
            '''
            @dataclass
            class ShippingAddress:
                """A plain record: the decorator writes __init__, __repr__ and __eq__."""

                city: str
                pin_code: str


            home = ShippingAddress("Pune", "411001")
            print(home)
            print(f"{home == ShippingAddress('Pune', '411001')=}")
            '''
        ),
    ]


def _class_statement_cells() -> list[NotebookNode]:
    """2.1.2 The class statement."""
    return [
        md(
            """
            ### 2.1.2 The `class` statement

            `class` is an **executable statement**, like `def` (1.10.1). When Python reaches it:

            1. It creates a fresh namespace (a dict).
            2. It **runs the class body** top to bottom inside that namespace. Every assignment
               and every `def` in the body becomes an entry.
            3. It calls the **metaclass**, normally `type`, as `type(name, bases, namespace)`.
               The result is the class object.
            4. It binds the class name to that object in the enclosing scope.

            The body is ordinary code, so `print` runs while the class is being defined, before
            any instance exists. Watch the namespace grow as the body runs.
            """
        ),
        code(
            '''
            print("before the class statement")


            class Checkout:
                """Prints while its body runs."""

                print("  class body starts")
                currency = "INR"
                print(f"  {sorted(name for name in locals() if not name.startswith('__'))=}")

                def total(self) -> int:
                    """Never called here."""
                    return 0

                print(f"  {sorted(name for name in locals() if not name.startswith('__'))=}")


            print("after the class statement")
            '''
        ),
        md(
            """
            Step 3 can be done by hand. Calling `type` with three arguments creates a class:
            a name, a tuple of base classes and a namespace dict. The result behaves exactly
            like a class written with the `class` statement; JavaScript's closest equivalent is
            a class expression or `Object.create(proto)`.
            """
        ),
        code(
            '''
            def describe_coupon(self: Any) -> str:
                """A plain function that becomes a method once it is in the namespace."""
                return f"{self.code}: {self.percent_off}% off"


            Coupon = type(
                "Coupon",
                (object,),
                {"percent_off": 10, "describe": describe_coupon, "__doc__": "Built by type()."},
            )
            welcome = Coupon()
            welcome.code = "WELCOME10"
            print(f"{welcome.describe()=}")
            print(f"{type(Coupon)=}, {Coupon.__name__=}, {Coupon.__bases__=}")
            print(f"{type(Checkout) is type=}  (every ordinary class is an instance of type)")
            '''
        ),
        md(
            """
            After creation, the namespace is stored as `ClassName.__dict__`. It is a
            **`mappingproxy`**: a read-only view of the real dict. You cannot write through it,
            but `setattr` (or `Checkout.currency = …`) works, because it goes through
            `type.__setattr__`, which also invalidates CPython's method-lookup caches.

            The keys include entries Python added for you: `__module__`, `__qualname__`,
            `__doc__`, descriptors for `__dict__` and `__weakref__`, and two newer ones:
            `__firstlineno__` and `__static_attributes__` (*New in 3.13*, explained in 2.1.3).
            """
        ),
        code(
            """
            print(f"{type(Checkout.__dict__).__name__=}")
            print(sorted(Checkout.__dict__))
            try:
                Checkout.__dict__["currency"] = "USD"
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            Checkout.currency = "USD"  # goes through type.__setattr__, which updates the real dict
            print(f"{Checkout.__dict__['currency']=}")
            """
        ),
        md(
            """
            #### Under the hood: the bytecode of a `class` statement

            Compiling a tiny class shows the steps above. `LOAD_BUILD_CLASS` pushes the built-in
            `__build_class__`, the class body is a separate **code object** turned into a
            function by `MAKE_FUNCTION`, and the `CALL` runs it: `__build_class__` executes the
            body function in a new namespace and then calls the metaclass. Code objects are
            shown by name only (their reprs contain memory addresses).

            > **Note:** opcode names change between Python versions; the shape stays the same.
            """
        ),
        code(
            """
            class_source = "class Demo:\\n    rate = 18\\n\\n    def total(self):\\n        return 0\\n"
            module_code = compile(class_source, "<demo>", "exec")
            for instruction in dis.get_instructions(module_code):
                if isinstance(instruction.argval, types.CodeType):
                    shown_argument = f"<code object {instruction.argval.co_name}>"
                else:
                    shown_argument = instruction.argrepr
                print(f"{instruction.opname:<20} {shown_argument}")
            """
        ),
    ]


def _object_creation_cells() -> list[NotebookNode]:
    """2.1.3 Object creation."""
    return [
        md(
            """
            ### 2.1.3 Object creation

            Calling a class, `StockItem("SOAP", 10)`, runs `type.__call__`, which does two
            separate steps:

            1. **`__new__(cls, *args)`** allocates and returns a new, empty instance. It is a
               static method that receives the class. The default, `object.__new__`, is almost
               always enough.
            2. **`__init__(self, *args)`** initializes that instance: it sets attributes. It
               must return `None`.

            JavaScript's `constructor` does both at once. The traced class below prints each
            step; notice the instance has an empty `__dict__` between the two.
            """
        ),
        code(
            '''
            class TracedOrder:
                """Prints each creation step."""

                def __new__(cls, order_id: str) -> Self:
                    print(f"__new__(cls={cls.__name__}, order_id={order_id!r}) allocates")
                    instance = super().__new__(cls)  # object.__new__ takes only the class
                    print(f"  allocated, vars={vars(instance)}")
                    return instance

                def __init__(self, order_id: str) -> None:
                    print(f"__init__(self, order_id={order_id!r}) fills in attributes")
                    self.order_id = order_id


            first_order = TracedOrder("ORD-1")
            print(f"{vars(first_order)=}")
            '''
        ),
        md(
            """
            The same two steps, done by hand. This is what `TracedOrder("ORD-2")` does for you.
            """
        ),
        code(
            """
            manual_order = TracedOrder.__new__(TracedOrder, "ORD-2")
            TracedOrder.__init__(manual_order, "ORD-2")
            print(f"{vars(manual_order)=}")
            """
        ),
        md(
            """
            When do you write `__new__`? Mainly when subclassing an **immutable** type such as
            `int`, `str` or `tuple`: by the time `__init__` runs the value is already fixed, so
            validation or conversion has to happen in `__new__`.
            """
        ),
        code(
            '''
            class Paise(int):
                """An int that refuses negative amounts; int is immutable, so this needs __new__."""

                def __new__(cls, amount: int) -> Self:
                    if amount < 0:
                        raise ValueError("amount cannot be negative")
                    return super().__new__(cls, amount)


            print(f"{Paise(2500) + 100=}, {isinstance(Paise(1), int)=}")
            print(raised_message(lambda: Paise(-1)))
            '''
        ),
        md(
            """
            If `__new__` returns something that is **not** an instance of the class,
            `type.__call__` skips `__init__` entirely. That is legal but surprising, so keep it
            for special cases (caching, singletons, factories).
            """
        ),
        code(
            '''
            class Surprising:
                """__new__ returns an int, so __init__ never runs."""

                def __new__(cls) -> Any:
                    return 42

                def __init__(self) -> None:
                    print("never printed")


            print(f"{Surprising()=}")
            '''
        ),
        md(
            """
            **Explicit `self`.** A method is an ordinary function whose first parameter receives
            the instance. `soap.ship(2)` is shorthand for `StockItem.ship(soap, 2)`. The name
            `self` is only a convention (any name works), but always use it.
            """
        ),
        code(
            """
            soap = StockItem("SOAP", 10)
            soap.ship(2)  # what you write
            StockItem.ship(soap, 2)  # what it means
            print(f"{soap.quantity=}")
            """
        ),
        md(
            """
            **Inspecting an instance.** `vars(instance)` returns the instance's own attribute
            dict (the same object as `instance.__dict__`). `instance.__class__` is its class,
            the same as `type(instance)`.

            `__static_attributes__` (*New in 3.13*) is a tuple of the names assigned through
            `self.<name>` anywhere in the class body, collected by the compiler. Tools use it
            to know an instance's likely attributes without creating one.
            """
        ),
        code(
            """
            print(f"{vars(soap)=}")
            print(f"{soap.__dict__ is vars(soap)=}")
            print(f"{soap.__class__=}, {type(soap) is soap.__class__=}")
            if sys.version_info >= (3, 13):
                print(f"{StockItem.__static_attributes__=}")
            else:
                print("__static_attributes__ needs Python 3.13+")
            """
        ),
        md(
            """
            #### Under the hood: what an instance costs

            An ordinary instance is a small header plus a pointer to its attribute storage.
            Since 3.11 CPython stores the attributes of most instances inline and only builds a
            real `__dict__` when you ask for one (`vars()` does). Instances of the same class
            share one key table (key-sharing dicts, 1.6.1). Unit 2.5 shows how `__slots__`
            removes the dict altogether.

            > **Note:** the byte counts depend on the Python version and platform.
            """
        ),
        code(
            """
            print(f"{sys.getsizeof(soap)=} bytes (the instance itself)")
            print(f"{sys.getsizeof(vars(soap))=} bytes (its materialized __dict__)")
            print(f"{sys.getsizeof(StockItem)=} bytes (the class object)")
            """
        ),
    ]


def _attributes_cells() -> list[NotebookNode]:
    """2.1.4 Instance vs class attributes."""
    return [
        md(
            """
            ### 2.1.4 Instance vs class attributes

            Assignments in the **class body** create **class attributes**, shared by every
            instance. Assignments to `self.<name>` create **instance attributes**, stored in each
            instance's own `__dict__`.

            Reading `instance.name` searches in this order (descriptors such as properties
            change this slightly; see 2.1.6 and 2.5):

            1. the instance's `__dict__`
            2. the class's `__dict__`
            3. each base class's `__dict__`, in MRO order (2.2.3)

            ```mermaid
            graph LR
                instance["soap.__dict__"] -->|not found| klass["Product.__dict__"]
                klass -->|not found| base["object.__dict__"]
                base -->|not found| error["AttributeError"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            soap.__dict__ --miss--> Product.__dict__ --miss--> object.__dict__ --miss--> AttributeError
            ```

            </details>
            """
        ),
        code(
            '''
            class Product:
                """currency is a class attribute; name and price are instance attributes."""

                currency = "INR"

                def __init__(self, name: str, price: int) -> None:
                    self.name = name
                    self.price = price


            soap = Product("Soap", 49)
            tea = Product("Tea", 120)
            print(f"{vars(soap)=}")
            print(f"{soap.currency=} (found on the class)")
            Product.currency = "USD"
            print(f"{tea.currency=} (every instance sees the change)")
            Product.currency = "INR"
            '''
        ),
        md(
            """
            **Shadowing.** Assigning through an instance never changes the class: it creates an
            instance attribute with the same name, which hides the class attribute for that one
            instance. Deleting it makes the class attribute visible again.
            """
        ),
        code(
            """
            tea.currency = "EUR"  # creates an instance attribute that shadows the class one
            print(f"{vars(tea)=}")
            print(f"{tea.currency=}, {soap.currency=}, {Product.currency=}")
            del tea.currency
            print(f"{tea.currency=} (the class attribute is visible again)")
            """
        ),
        md(
            """
            The lookup continues into base classes. `find_attribute_owner` repeats the search
            by hand (without descriptors) to show where each name is found. `__repr__` comes
            all the way from `object`.
            """
        ),
        code(
            '''
            def find_attribute_owner(instance: object, attribute_name: str) -> str:
                """Report where attribute lookup finds attribute_name (ignoring descriptors)."""
                if attribute_name in vars(instance):
                    return "instance __dict__"
                for klass in type(instance).__mro__:
                    if attribute_name in vars(klass):
                        return f"class {klass.__name__}"
                return "not found -> AttributeError"


            class DigitalProduct(Product):
                """Adds a class attribute of its own."""

                shipping_required = False


            ebook = DigitalProduct("Python e-book", 499)
            for attribute_name in ["name", "shipping_required", "currency", "__repr__", "weight"]:
                print(f"{attribute_name:<18} -> {find_attribute_owner(ebook, attribute_name)}")
            '''
        ),
        md(
            """
            **The shared mutable class-attribute trap.** A mutable value (list, dict, set) in
            the class body is created **once**, when the class body runs, and every instance
            shares it. `self.line_items.append(...)` does not assign, it mutates the shared list.

            > **Warning:** this is the opposite of JavaScript. In JS, a class field
            > `lineItems = [];` runs once **per instance**, inside the constructor.
            """
        ),
        code(
            '''
            class Invoice:
                """BUG: line_items is one list shared by every invoice."""

                line_items: list[str] = []

                def add_line(self, description: str) -> None:
                    """Append a line (mutates the shared class attribute)."""
                    self.line_items.append(description)


            march_invoice = Invoice()
            april_invoice = Invoice()
            march_invoice.add_line("Hosting")
            print(f"{april_invoice.line_items=}")
            print(f"{march_invoice.line_items is Invoice.line_items=}")
            '''
        ),
        md(
            """
            The fix: create mutable state in `__init__`, so each instance gets its own object.
            """
        ),
        code(
            '''
            class FixedInvoice:
                """Each invoice gets its own list."""

                def __init__(self) -> None:
                    self.line_items: list[str] = []

                def add_line(self, description: str) -> None:
                    """Append a line to this invoice only."""
                    self.line_items.append(description)


            march_invoice = FixedInvoice()
            april_invoice = FixedInvoice()
            march_invoice.add_line("Hosting")
            print(f"{march_invoice.line_items=}, {april_invoice.line_items=}")
            '''
        ),
        *predict_cells(
            """
            class Team:
                size = 0
                members = []

            alpha, beta = Team(), Team()
            alpha.size += 1
            alpha.members += ["Asha"]
            print(Team.size, beta.size, Team.members)
            print("size" in vars(alpha), "members" in vars(alpha))
            """,
            """
            ```text
            0 0 ['Asha']
            True True
            ```

            `alpha.size += 1` reads `Team.size` (0), adds 1 and **assigns** to `alpha.size`,
            creating an instance attribute; the class keeps 0. `alpha.members += ["Asha"]`
            calls `list.__iadd__`, which **mutates the shared list in place**, and then also
            assigns the same list to `alpha.members`. So both names end up in `vars(alpha)`,
            but only the list change is visible to `beta` and the class.
            """,
            """
            class Team:
                size: int = 0
                members: list[str] = []


            alpha, beta = Team(), Team()
            alpha.size += 1
            alpha.members += ["Asha"]
            print(Team.size, beta.size, Team.members)
            print("size" in vars(alpha), "members" in vars(alpha))
            """,
        ),
        md(
            """
            **Good uses of class attributes:** constants and counters. Constants use
            `UPPER_CASE` (PEP 8) and can be annotated `ClassVar` so type checkers know they
            belong to the class. A counter must be updated **through the class**
            (`Ticket.issued_count += 1`); updating it through `self` would create an instance
            attribute, as the predict question showed.
            """
        ),
        code(
            '''
            class Ticket:
                """Class constants in UPPER_CASE; a class-level counter for ticket numbers."""

                MAX_SEATS: ClassVar[int] = 4
                issued_count: ClassVar[int] = 0

                def __init__(self, seats: int) -> None:
                    if not 1 <= seats <= Ticket.MAX_SEATS:
                        raise ValueError(f"seats must be 1-{Ticket.MAX_SEATS}")
                    Ticket.issued_count += 1  # write through the class, not self
                    self.ticket_number = Ticket.issued_count
                    self.seats = seats


            tickets = [Ticket(2), Ticket(1), Ticket(4)]
            print(f"{[ticket.ticket_number for ticket in tickets]=}, {Ticket.issued_count=}")
            print(raised_message(lambda: Ticket(9)))
            '''
        ),
        md(
            """
            The broken version: `self.issued_count += 1` reads the class value (0) and writes
            an instance attribute every time, so the class counter never moves.
            """
        ),
        code(
            '''
            class BrokenTicket:
                """BUG: the counter is updated through self."""

                issued_count = 0

                def __init__(self) -> None:
                    self.issued_count += 1  # reads the class value, writes an instance attribute


            broken_tickets = [BrokenTicket(), BrokenTicket()]
            print(f"{BrokenTicket.issued_count=}")
            print(f"{[ticket.issued_count for ticket in broken_tickets]=}")
            '''
        ),
    ]


def _methods_cells() -> list[NotebookNode]:
    """2.1.5 Methods."""
    return [
        md(
            """
            ### 2.1.5 Methods

            A function stored on a class is a plain function. When you read it **through an
            instance**, Python returns a **bound method**: a small object that remembers the
            function (`__func__`) and the instance (`__self__`). Calling the bound method calls
            the function with the instance as the first argument.

            `Money` below is the start of a value type that Unit 2.4 will turn into a full
            numeric class.
            """
        ),
        code(
            '''
            class Money:
                """An amount of money in one currency (Unit 2.4 adds arithmetic)."""

                def __init__(self, amount: Decimal, currency: str = "INR") -> None:
                    self.amount = amount
                    self.currency = currency

                def formatted(self) -> str:
                    """Return e.g. 'INR 250.00'."""
                    return f"{self.currency} {self.amount:.2f}"


            price = Money(Decimal("250"))
            print(f"{type(Money.formatted).__name__=}  (a plain function on the class)")
            bound_formatted = price.formatted
            print(f"{type(bound_formatted).__name__=}")
            print(f"{bound_formatted.__self__ is price=}")
            print(f"{bound_formatted.__func__ is Money.formatted=}")
            print(f"{bound_formatted()=}")
            '''
        ),
        md(
            """
            Because the bound method carries its instance, you can store it, pass it as a
            callback or put it in a dict, and it still works. No `.bind(this)` is ever needed.

            Each attribute access builds a **new** bound-method object, so `is` is `False`,
            but two bound methods of the same function and instance compare equal.
            """
        ),
        code(
            """
            callbacks: list[Callable[[], str]] = [
                Money(Decimal("99")).formatted,
                Money(Decimal("5"), "USD").formatted,
            ]
            print([callback() for callback in callbacks])
            print(f"{price.formatted is price.formatted=}  (a new bound method on each access)")
            print(f"{price.formatted == price.formatted=}")
            """
        ),
        md(
            """
            #### Under the hood: binding is the descriptor protocol

            Functions have a `__get__` method. When attribute lookup finds a function on the
            class, it calls `function.__get__(instance, owner)`, which returns the bound method.
            `types.MethodType(function, instance)` builds the same object directly. Unit 2.5
            covers descriptors in full; `@property`, `@classmethod` and `@staticmethod` all use
            this hook.
            """
        ),
        code(
            """
            function_object = Money.__dict__["formatted"]
            manually_bound = function_object.__get__(price, Money)
            print(f"{manually_bound()=}, {type(manually_bound) is types.MethodType=}")
            print(f"{types.MethodType(function_object, price)()=}")
            """
        ),
        md(
            """
            **`@classmethod`** receives the **class** as its first argument (`cls`) instead of
            an instance. Its classic use is an **alternative constructor**: another way to build
            an instance, named after its input (`from_string`, `from_paise`). Because it calls
            `cls(...)` rather than `Money(...)`, it builds whichever class it was called on.

            **`@staticmethod`** receives neither. It is a plain function that lives in the class
            namespace because it belongs to the class conceptually (here, currency-code
            validation used by the constructors).
            """
        ),
        code(
            '''
            class Money:
                """An amount of money in one currency."""

                def __init__(self, amount: Decimal, currency: str = "INR") -> None:
                    if not Money.is_valid_currency(currency):
                        raise ValueError(f"invalid currency code: {currency!r}")
                    self.amount = amount
                    self.currency = currency

                @classmethod
                def from_string(cls, text: str) -> Self:
                    """Parse 'INR 250.00' (alternative constructor)."""
                    currency, amount_text = text.split()
                    return cls(Decimal(amount_text), currency)

                @classmethod
                def from_paise(cls, paise: int) -> Self:
                    """Build an INR amount from whole paise."""
                    return cls(Decimal(paise) / 100, "INR")

                @staticmethod
                def is_valid_currency(code: str) -> bool:
                    """Three upper-case letters, like 'INR' or 'USD'."""
                    return len(code) == 3 and code.isalpha() and code.isupper()

                def formatted(self) -> str:
                    """Return e.g. 'INR 250.00'."""
                    return f"{self.currency} {self.amount:.2f}"


            print(f"{Money.from_string('USD 19.99').formatted()=}")
            print(f"{Money.from_paise(25_050).formatted()=}")
            '''
        ),
        md(
            """
            **Subclass-aware.** `Refund` inherits `from_paise`, and because the method uses
            `cls`, `Refund.from_paise(...)` returns a `Refund`. A version that hard-codes
            `Money(...)` silently returns the wrong type for every subclass.
            """
        ),
        code(
            '''
            class Refund(Money):
                """Money flowing back to a customer."""

                def formatted(self) -> str:
                    """Prefix the amount with a minus sign."""
                    return f"-{super().formatted()}"


            class HardCodedMoney(Money):
                """BUG: the alternative constructor ignores cls."""

                @classmethod
                def from_paise(cls, paise: int) -> Money:
                    return Money(Decimal(paise) / 100, "INR")


            class HardCodedRefund(HardCodedMoney):
                """Inherits the broken constructor."""


            refund = Refund.from_paise(4_950)
            print(f"{type(refund).__name__=}, {refund.formatted()=}")
            print(f"{type(HardCodedRefund.from_paise(4_950)).__name__=}  (wrong class)")
            '''
        ),
        md(
            """
            In application code the most common alternative constructor is **`from_dict`**:
            building an object from a JSON payload or a database row. The same `cls(...)` rule
            makes it subclass-aware. (Lab 2.1 exercise 3 asks for a stricter one, with
            validation and cleaning.)
            """
        ),
        code(
            '''
            class ApiMoney(Money):
                """Money as it arrives in JSON payloads."""

                @classmethod
                def from_dict(cls, payload: Mapping[str, str]) -> Self:
                    """Build from {"amount": "250.00", "currency": "INR"}."""
                    return cls(Decimal(payload["amount"]), payload.get("currency", "INR"))


            class ApiRefund(ApiMoney):
                """Inherits from_dict and gets ApiRefund instances from it."""


            payload = {"amount": "99.90", "currency": "USD"}
            print(f"{ApiMoney.from_dict(payload).formatted()=}")
            print(f"{type(ApiRefund.from_dict({'amount': '10'})).__name__=}")
            '''
        ),
        md(
            """
            The standard library uses the same pattern everywhere: `dict.fromkeys`,
            `int.from_bytes`, `date.fromisoformat`, `Decimal.from_float`. Each one is a
            `classmethod`, so subclasses of these types get instances of themselves.
            """
        ),
        code(
            """
            print(f"{dict.fromkeys(['soap', 'tea'], 0)=}")
            print(f"{int.from_bytes(bytes([1, 0]), 'big')=}")
            print(f"{date.fromisoformat('2026-11-07')=}")
            print(f"{Decimal.from_float(0.5)=}")
            print(f"{type(dict.__dict__['fromkeys']).__name__=}")
            """
        ),
        md(
            """
            A static method can be called through the class or an instance; it receives no
            automatic argument either way.
            """
        ),
        code(
            """
            print(f"{Money.is_valid_currency('INR')=}")
            print(f"{Money.from_paise(100).is_valid_currency('rupees')=}")
            print(raised_message(lambda: Money(Decimal("1"), "inr")))
            """
        ),
        md(
            """
            **Decision table**

            | Kind | First argument | Use it when | Example |
            | --- | --- | --- | --- |
            | Instance method | `self` (the instance) | It reads or changes one object's state | `cart.add(item)` |
            | `@classmethod` | `cls` (the class it was called on) | It builds instances or works with class-level data | `Money.from_paise(500)` |
            | `@staticmethod` | nothing | It is a helper that belongs with the class but needs no state | `Money.is_valid_currency("INR")` |
            | Module-level function | nothing | It does not belong to any one class | `add_gst(amount)` |

            The cell calls each kind through an instance, a subclass instance and the subclass
            itself. Notice that `cls` follows the subclass, and that an instance method called on
            the class has no `self` to receive.
            """
        ),
        code(
            '''
            class MethodKinds:
                """One method of each kind."""

                def instance_method(self) -> str:
                    return f"self is a {type(self).__name__} instance"

                @classmethod
                def class_method(cls) -> str:
                    return f"cls is {cls.__name__}"

                @staticmethod
                def static_method() -> str:
                    return "nothing passed"


            class SubKinds(MethodKinds):
                """Inherits all three."""


            for caller in [MethodKinds(), SubKinds(), SubKinds]:
                caller_label = getattr(caller, "__name__", f"{type(caller).__name__}()")
                for method_name in ["instance_method", "class_method", "static_method"]:
                    result = raised_message(getattr(caller, method_name))
                    if result == "no error":
                        result = getattr(caller, method_name)()
                    print(f"{caller_label:<14} {method_name:<16} {result}")
            '''
        ),
    ]


def _properties_cells() -> list[NotebookNode]:
    """2.1.6 Properties."""
    return [
        md(
            """
            ### 2.1.6 Properties

            `@property` turns a method into an attribute that runs code when it is read.
            Callers write `plan.total_fee`, not `plan.total_fee()`. Add a `.setter` to run code
            on assignment and a `.deleter` to run code on `del`.

            | Pattern | How | Example below |
            | --- | --- | --- |
            | Computed attribute | getter only, derived from other state | `total_fee` |
            | Read-only attribute | getter only, backed by `_name` | `subscription_id` |
            | Validation on assignment | getter + setter that checks, then stores `_name` | `months` |
            | Clean-up on delete | getter + setter + deleter | `auth_token` |

            First, a computed and a read-only property. Assigning to either raises
            `AttributeError`, and the computed value is recalculated after `months` changes.
            """
        ),
        code(
            '''
            class Subscription:
                """A paid plan billed monthly."""

                def __init__(self, subscription_id: str, monthly_fee: Decimal, months: int) -> None:
                    self._subscription_id = subscription_id
                    self.monthly_fee = monthly_fee
                    self.months = months

                @property
                def subscription_id(self) -> str:
                    """Read-only: there is no setter."""
                    return self._subscription_id

                @property
                def total_fee(self) -> Decimal:
                    """Computed on every access."""
                    return self.monthly_fee * self.months


            plan = Subscription("SUB-7", Decimal("299"), 12)
            print(f"{plan.total_fee=}")
            plan.months = 6
            print(f"{plan.total_fee=} (recomputed)")
            for attribute_name in ["subscription_id", "total_fee"]:
                print(raised_message(functools.partial(setattr, plan, attribute_name, "x")))
            '''
        ),
        md(
            """
            **Validation on assignment.** The subclass adds a `months` property whose setter
            rejects bad values. The inherited `__init__` already does `self.months = months`, and
            that assignment now goes through the setter too, so validation also happens at
            construction. A failed assignment leaves the old value in place.
            """
        ),
        code(
            '''
            class ValidatedSubscription(Subscription):
                """months must be a whole number from 1 to 36, on every assignment."""

                @property
                def months(self) -> int:
                    """Billing period in months."""
                    return self._months

                @months.setter
                def months(self, value: int) -> None:
                    if not isinstance(value, int) or not 1 <= value <= 36:
                        raise ValueError(f"months must be an int from 1 to 36, got {value!r}")
                    self._months = value


            plan = ValidatedSubscription("SUB-8", Decimal("299"), 12)
            print(raised_message(lambda: setattr(plan, "months", 48)))
            print(f"{plan.months=} (unchanged after the failed assignment)")
            print(raised_message(lambda: ValidatedSubscription("SUB-9", Decimal("99"), 0)))
            '''
        ),
        md(
            """
            **Deleter.** `del session.auth_token` runs the deleter, which can clean up instead
            of just removing a value. Here it records a logout and leaves the token as `None`.
            """
        ),
        code(
            '''
            class UserSession:
                """A login session whose token can be revoked with del."""

                def __init__(self, username: str) -> None:
                    self.username = username
                    self._auth_token: str | None = None
                    self.events: list[str] = []

                @property
                def auth_token(self) -> str | None:
                    """The current token, or None when logged out."""
                    return self._auth_token

                @auth_token.setter
                def auth_token(self, token: str) -> None:
                    self._auth_token = token
                    self.events.append("login")

                @auth_token.deleter
                def auth_token(self) -> None:
                    self._auth_token = None
                    self.events.append("logout")


            session = UserSession("asha")
            session.auth_token = "tok_123"
            del session.auth_token
            print(f"{session.auth_token=}, {session.events=}")
            '''
        ),
        md(
            """
            `@property` is shorthand for `property(fget, fset, fdel, doc)`. The decorator form
            is preferred, but the call form shows what a property object holds: up to three
            functions and a docstring.
            """
        ),
        code(
            '''
            class SpeakerVolume:
                """Volume clamped to 0-10, written with the property() call form."""

                def __init__(self) -> None:
                    self._level = 5

                def _get_level(self) -> int:
                    return self._level

                def _set_level(self, value: int) -> None:
                    self._level = max(0, min(10, value))

                level = property(_get_level, _set_level, doc="Volume from 0 to 10, clamped.")


            speaker = SpeakerVolume()
            speaker.level = 14
            print(f"{speaker.level=}")
            months_property = ValidatedSubscription.__dict__["months"]
            print(f"{type(months_property).__name__=}, {months_property.fget.__name__=}")
            print(f"{months_property.fset is not None=}, {months_property.fdel=}")
            print(f"{SpeakerVolume.level.__doc__=}")
            '''
        ),
        md(
            """
            **Uniform access principle.** Callers should not care whether a value is stored or
            computed. Start with a plain attribute; if you later need validation or
            normalization, turn it into a property and **no caller changes**. That is why Python
            code does not write `get_email()` / `set_email()` "just in case", as Java code
            often does. JavaScript getters and setters give the same freedom.
            """
        ),
        code(
            '''
            def send_welcome(account: Any) -> str:
                """Client code: only reads account.email."""
                return f"Welcome mail to {account.email}"


            class AccountV1:
                """Version 1: a plain attribute."""

                def __init__(self, email: str) -> None:
                    self.email = email


            class AccountV2:
                """Version 2: the same name, now a normalizing property."""

                def __init__(self, email: str) -> None:
                    self.email = email  # goes through the setter

                @property
                def email(self) -> str:
                    return self._email

                @email.setter
                def email(self, value: str) -> None:
                    self._email = value.strip().lower()


            for account_class in [AccountV1, AccountV2]:
                print(f"{account_class.__name__}: {send_welcome(account_class('  Asha@Example.com '))!r}")
            '''
        ),
        md(
            """
            A computed property runs on **every** read. For an expensive value that does not
            change, `functools.cached_property` computes it once and stores the result in the
            instance `__dict__`; later reads never call the function again.
            """
        ),
        code(
            '''
            class SalesSummary:
                """grand_total is computed once, on first access."""

                def __init__(self, daily_sales: list[int]) -> None:
                    self.daily_sales = daily_sales

                @functools.cached_property
                def grand_total(self) -> int:
                    """Sum of every day's sales."""
                    print("  computing grand_total ...")
                    return sum(self.daily_sales)


            summary = SalesSummary([1200, 950, 1430])
            print(f"{summary.grand_total=}")
            print(f"{summary.grand_total=}  (no 'computing' line: cached)")
            print(f"{vars(summary)=}")
            '''
        ),
        md(
            """
            #### Under the hood: a property beats the instance `__dict__`

            A property is a **data descriptor** stored on the class (it defines `__set__`), and
            data descriptors take priority over the instance `__dict__` during lookup. Even if
            a value with the same name is forced into `vars(plan)`, the property still answers.
            Unit 2.5 explains the full lookup order.
            """
        ),
        code(
            """
            plan = Subscription("SUB-10", Decimal("100"), 3)
            vars(plan)["total_fee"] = Decimal("0")  # sneak a value into the instance dict
            print(f"{vars(plan)=}")
            print(f"{plan.total_fee=} (the property on the class still wins)")
            print(f"{inspect.isdatadescriptor(Subscription.__dict__['total_fee'])=}")
            """
        ),
    ]


def _encapsulation_cells() -> list[NotebookNode]:
    """2.1.7 Encapsulation by convention."""
    return [
        md(
            """
            ### 2.1.7 Encapsulation by convention

            Python has no `private` keyword. Instead:

            - **`_name`** (one underscore) means "internal, not part of the public API". Nothing
              enforces it; it is a message to other developers. Tools respect it:
              `from module import *` skips underscore names and IDEs hide them from completion.
            - **`__name`** (two leading underscores, at most one trailing) triggers **name
              mangling**: inside a class body the compiler rewrites it to `_ClassName__name`.

            The motto is "we are all consenting adults": the underscore warns, it does not lock.
            """
        ),
        code(
            '''
            class PaymentClient:
                """Public method send(); everything with an underscore is internal."""

                def __init__(self, api_key: str) -> None:
                    self._api_key = api_key  # internal: please do not touch

                def _sign(self, payload: str) -> str:
                    return f"{payload}|signed-with-{self._api_key[-4:]}"

                def send(self, payload: str) -> str:
                    """Sign and 'send' a payload."""
                    return self._sign(payload)


            client = PaymentClient("sk_test_12345678")
            print(client.send("amount=500"))
            print(f"{client._api_key=}  (reachable: the underscore is only a warning)")
            '''
        ),
        md(
            """
            **Name mangling.** `self.__pin` is stored as `_Vault__pin`. Code outside the class
            that writes `vault.__pin` is not mangled, so it fails; the mangled name still works
            for anyone who really wants it.
            """
        ),
        code(
            '''
            class Vault:
                """Stores a PIN under a mangled name."""

                def __init__(self, pin: str) -> None:
                    self.__pin = pin  # stored as _Vault__pin

                def check(self, attempt: str) -> bool:
                    """Compare an attempt with the stored PIN."""
                    return attempt == self.__pin


            vault = Vault("4321")
            print(f"{vars(vault)=}")
            print(f"{vault.check('4321')=}")
            print(raised_message(lambda: vault.__pin))
            print(f"{vault._Vault__pin=}  (still reachable by the mangled name)")
            '''
        ),
        md(
            """
            Mangling exists to prevent **accidental name clashes in subclasses**, not to hide
            data. Here `Cache` and its subclass both use `__entries`, but they end up as two
            different attributes, so the subclass cannot break the base class by accident.
            """
        ),
        code(
            '''
            class Cache:
                """Base class with its own private storage."""

                def __init__(self) -> None:
                    self.__entries: dict[str, str] = {}  # becomes _Cache__entries

                def cache_size(self) -> int:
                    """Entries in the base-class storage."""
                    return len(self.__entries)


            class UserCache(Cache):
                """Reuses the name __entries without clobbering the base class."""

                def __init__(self) -> None:
                    super().__init__()
                    self.__entries = ["recent", "users"]  # becomes _UserCache__entries


            user_cache = UserCache()
            print(f"{vars(user_cache)=}")
            print(f"{user_cache.cache_size()=}  (the base class still sees its own dict)")
            '''
        ),
        md(
            """
            #### Under the hood: mangling happens at compile time

            The rewrite is done by the compiler, so the mangled name is already in the
            method's code object (`co_names`). Strings passed to `getattr` / `hasattr` are never
            mangled, and dunder names such as `__init__` (two trailing underscores) are left
            alone.
            """
        ),
        code(
            """
            print(f"{Vault.check.__code__.co_names=}")
            mangled_name = "_Vault__pin"
            print(f"{getattr(vault, mangled_name)=}")
            print(f"{hasattr(vault, '__pin')=}  (strings are not mangled)")
            """
        ),
        md(
            """
            **Comparison with JavaScript and TypeScript**

            | | Python `_x` | Python `__x` | TypeScript `private x` | JavaScript `#x` |
            | --- | --- | --- | --- | --- |
            | Enforced by | nobody (convention) | the compiler renames it | the TS compiler only; erased at run time | the JS engine |
            | Reachable from outside | yes | yes, as `obj._Class__x` | yes, at run time | no (`SyntaxError` outside the class) |
            | Visible to reflection | `vars(obj)` | `vars(obj)` (mangled) | `Object.keys(obj)` | no |
            | Main purpose | mark internal API | avoid subclass clashes | design-time checking | real privacy |

            > **Note:** prefer a single underscore. Use `__x` only when you expect subclasses
            > from other authors that might reuse the name. Python's closest match to `#x` is a
            > closure variable (1.11), which really is unreachable from outside.
            """
        ),
    ]


def _js_bridge_cells() -> list[NotebookNode]:
    """2.1.8 JS bridge."""
    return [
        md(
            """
            ### 2.1.8 JS bridge

            **Classes vs prototypes.** JavaScript classes are syntax over prototypes: every
            object has a hidden `[[Prototype]]` link, and methods live on `Class.prototype`.
            Python has no per-object prototype link. Every instance has a `__class__`, methods
            live in the class's `__dict__`, and lookup walks the class's `__mro__`.

            | JavaScript | Python |
            | --- | --- |
            | `Object.getPrototypeOf(obj)` | `type(obj)` / `obj.__class__` |
            | prototype chain | `type(obj).__mro__` |
            | `Counter.prototype.reset = function () {}` | `Counter.reset = reset` |
            | `Object.setPrototypeOf(obj, Other.prototype)` | `obj.__class__ = Other` (only for compatible layouts; rarely wise) |
            | `this` set by the call site (`obj.m()`, `m()`, `new`, `call`, `apply`, `bind`) | `self` bound when the method is read from the instance |
            | arrow functions capture the outer `this` | lambdas and closures capture `self` like any other variable |
            | `static m()`: `this` is the constructor | `@classmethod`: `cls` is the class it was called on |
            | `new Counter()` | `Counter()`: a class is called like a function |

            **`self` vs `this`.** In JavaScript, pulling a method off its object loses `this`:

            ```javascript
            class ClickCounter {
              count = 0;
              increment() { this.count += 1; }
            }
            const counter = new ClickCounter();
            const increment = counter.increment;
            increment();                          // TypeError: cannot read 'count' of undefined
            button.addEventListener("click", counter.increment);  // same bug
            const fixed = counter.increment.bind(counter);         // the usual fix
            ```

            In Python the bound method already carries the instance, so the same code just works.
            """
        ),
        code(
            '''
            class ClickCounter:
                """Counts clicks."""

                def __init__(self) -> None:
                    self.count = 0

                def increment(self) -> None:
                    """Add one click."""
                    self.count += 1


            click_counter = ClickCounter()
            increment = click_counter.increment  # self is already bound
            for _ in range(3):
                increment()
            handlers: dict[str, Callable[[], None]] = {"click": click_counter.increment}
            handlers["click"]()
            print(f"{click_counter.count=}")
            '''
        ),
        md(
            """
            Like adding to `ClickCounter.prototype`, adding a function to a Python class later
            makes it available to **existing** instances, because lookup reaches the class at
            call time. The second line shows the Python view of the "prototype chain".
            """
        ),
        code(
            '''
            def reset(self: ClickCounter) -> None:
                """Set the count back to zero."""
                self.count = 0


            ClickCounter.reset = reset  # like ClickCounter.prototype.reset = function () {...}
            click_counter.reset()
            print(f"{click_counter.count=}")
            print(f"{[klass.__name__ for klass in type(click_counter).__mro__]=}")
            '''
        ),
        *predict_cells(
            """
            class Greeter:
                def __init__(self, name):
                    self.name = name

                def greet(self):
                    return f"Hi, I am {self.name}"

            asha = Greeter("Asha")
            say_hello = asha.greet
            asha.name = "Asha K"
            print(say_hello())
            print(Greeter.greet(asha))
            print(Greeter.greet())
            """,
            """
            ```text
            Hi, I am Asha K
            Hi, I am Asha K
            TypeError: Greeter.greet() missing 1 required positional argument: 'self'
            ```

            `say_hello` is bound to the **object**, not to a snapshot of its attributes, so it
            sees the new name. `Greeter.greet(asha)` passes the instance explicitly. Reading the
            method from the **class** gives the plain function, and with no instance there is
            nothing to fill `self`: Python's version of JavaScript's lost `this`, except it
            fails loudly with a clear message.
            """,
            '''
            class Greeter:
                """Says hello."""

                def __init__(self, name: str) -> None:
                    self.name = name

                def greet(self) -> str:
                    """Introduce yourself."""
                    return f"Hi, I am {self.name}"


            asha = Greeter("Asha")
            say_hello = asha.greet
            asha.name = "Asha K"
            print(say_hello())
            print(Greeter.greet(asha))
            print(raised_message(lambda: Greeter.greet()))  # type: ignore[call-arg]
            ''',
        ),
    ]


def _pillars_cells() -> list[NotebookNode]:
    """2.1.9 The four pillars of OOP in Python."""
    return [
        md(
            """
            ### 2.1.9 The four pillars of OOP in Python

            The four classic pillars all exist in Python, but they look lighter than in Java
            or TypeScript, and this phase covers each one:

            | Pillar | Where in this phase | Python mechanism | Java | TypeScript |
            | --- | --- | --- | --- | --- |
            | Encapsulation | 2.1.6–2.1.7 | properties, `_name` convention, name mangling | `private` fields + getters/setters | `private` (compile time), `#x` (run time) |
            | Inheritance | 2.2 | `class B(A)`, **multiple** inheritance, C3 MRO, mixins | single `extends` + `implements` | single `extends`, mixin functions |
            | Polymorphism | 2.3.4, 2.4 | duck typing, special (dunder) methods, `singledispatch` | overriding + overloading by signature | structural typing, overload signatures (types only) |
            | Abstraction | 2.3 | ABCs (checked at instantiation), Protocols (checked by type checkers) | `abstract class`, `interface` | `abstract class`, `interface` (erased at run time) |

            The four cells below show one pillar each on a tiny media library.

            **Encapsulation**: a read-only property protects the size.
            """
        ),
        code(
            '''
            class MediaFile:
                """A file in a media library."""

                def __init__(self, name: str, size_bytes: int) -> None:
                    self.name = name
                    self._size_bytes = size_bytes

                @property
                def size_bytes(self) -> int:
                    """Read-only size."""
                    return self._size_bytes

                def summary(self) -> str:
                    """One-line description."""
                    return f"{self.name} ({self.size_bytes:,} bytes)"


            print(MediaFile("notes.txt", 2_048).summary())
            print(raised_error_name(lambda: setattr(MediaFile("x", 1), "size_bytes", 0)))
            '''
        ),
        md(
            """
            **Inheritance**: `AudioFile` reuses `MediaFile` and extends `summary()` with
            `super()` (Unit 2.2).
            """
        ),
        code(
            '''
            class AudioFile(MediaFile):
                """A media file with a duration."""

                def __init__(self, name: str, size_bytes: int, duration_seconds: int) -> None:
                    super().__init__(name, size_bytes)
                    self.duration_seconds = duration_seconds

                def summary(self) -> str:
                    """Add the duration to the base summary."""
                    minutes, seconds = divmod(self.duration_seconds, 60)
                    return f"{super().summary()}, {minutes}:{seconds:02d}"


            print(AudioFile("raga.mp3", 4_500_000, 245).summary())
            '''
        ),
        md(
            """
            **Polymorphism**: the loop calls `summary()` without knowing the type. `VideoLink`
            shares no base class with the others; having the method is enough (duck typing,
            2.3.4).
            """
        ),
        code(
            '''
            class VideoLink:
                """Not a MediaFile at all, but it has summary()."""

                def __init__(self, url: str) -> None:
                    self.url = url

                def summary(self) -> str:
                    """One-line description."""
                    return f"link to {self.url}"


            library = [MediaFile("notes.txt", 2_048), AudioFile("raga.mp3", 4_500_000, 245)]
            library.append(VideoLink("https://example.com/talk"))
            for item in library:
                print(item.summary())
            '''
        ),
        md(
            """
            **Abstraction**: an abstract base class (Unit 2.3) states what every playable item
            must provide, and refuses to create incomplete objects.
            """
        ),
        code(
            '''
            class Playable(ABC):
                """Anything that can be played."""

                @abstractmethod
                def play(self) -> str:
                    """Start playback and describe it."""


            class Podcast(Playable):
                """A concrete playable item."""

                def play(self) -> str:
                    return "playing podcast"


            print(Podcast().play())
            print(raised_message(Playable))
            '''
        ),
        md(
            """
            **How Python differs from Java/TypeScript in practice**

            - **No access modifiers.** Encapsulation is a convention plus properties, not a
              compiler rule (2.1.7).
            - **Multiple inheritance is allowed**, made safe by the C3 MRO and cooperative
              `super()` (2.2.2–2.2.4). Java and TypeScript allow one base class.
            - **No method overloading.** A class namespace is a dict, so a second `def` with
              the same name **replaces** the first. Python uses default arguments,
              `*args`/`**kwargs` or `functools.singledispatchmethod` instead.
            - **Interfaces are optional.** Duck typing works with no declaration at all;
              Protocols (2.3.3) add TypeScript-style structural checks for type checkers.

            The cell shows the "no overloading" rule: only the second `add` exists.
            """
        ),
        code(
            '''
            class Calculator:
                """Two methods with the same name: the second replaces the first."""

                def add(self, first: int, second: int) -> int:
                    return first + second

                def add(self, first: int, second: int, third: int) -> int:  # replaces the first
                    return first + second + third


            print(f"{Calculator().add(1, 2, 3)=}")
            print(raised_message(lambda: Calculator().add(1, 2)))  # type: ignore[call-arg]
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 2.1."""
    return [
        md(
            """
            ### Lab 2.1

            Four exercises. For each, replace every `raise NotImplementedError` in the stub,
            then run the check cell. Until then the checks print FAIL; that is expected. Two
            structural checks ("is a classmethod" in exercise 3, "line_total is a property" in
            exercise 4) already pass on the stub, because the stub has the right shape.

            #### Exercise 1 — `BankAccount` with a validated balance and history

            `BankAccount(owner, opening_balance=Decimal("0"))`:

            - `balance` is a **read-only** property (assigning to it raises `AttributeError`).
            - `deposit(amount)` and `withdraw(amount)` return the new balance. The amount must be
              a `Decimal` (otherwise `TypeError(f"amount must be a Decimal, got {type_name}")`)
              and greater than zero (otherwise `ValueError("amount must be positive")`).
            - A withdrawal larger than the balance raises
              `ValueError(f"insufficient funds: balance {balance:.2f}, requested {amount:.2f}")`.
            - `history` is a property returning a **tuple** of `Transaction` records, oldest
              first. The first one is `Transaction("open", opening_balance, opening_balance)`;
              then `"deposit"` / `"withdrawal"` with the balance after each.
            - A failed operation changes nothing. A negative opening balance raises
              `ValueError("opening balance cannot be negative")`; a non-`Decimal` one raises
              `TypeError(f"opening_balance must be a Decimal, got {type_name}")`.
            """
        ),
        code(
            '''
            class Transaction(NamedTuple):
                """One entry in a BankAccount history."""

                kind: str  # "open", "deposit" or "withdrawal"
                amount: Decimal
                balance_after: Decimal


            class BankAccount:
                """A bank account with a read-only, validated balance and an append-only history."""

                def __init__(self, owner: str, opening_balance: Decimal = Decimal("0")) -> None:
                    raise NotImplementedError("Lab 2.1: implement BankAccount.__init__")

                @property
                def balance(self) -> Decimal:
                    """Current balance (read-only)."""
                    raise NotImplementedError("Lab 2.1: implement BankAccount.balance")

                @property
                def history(self) -> tuple[Transaction, ...]:
                    """Every transaction so far, oldest first."""
                    raise NotImplementedError("Lab 2.1: implement BankAccount.history")

                def deposit(self, amount: Decimal) -> Decimal:
                    """Add amount and return the new balance."""
                    raise NotImplementedError("Lab 2.1: implement BankAccount.deposit")

                def withdraw(self, amount: Decimal) -> Decimal:
                    """Take amount and return the new balance."""
                    raise NotImplementedError("Lab 2.1: implement BankAccount.withdraw")
            '''
        ),
        md("Run the checks."),
        code(
            '''
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
                """True if the returned history is a tuple and the account still has 3 entries."""
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
            '''
        ),
        md(
            """
            #### Exercise 2 — `Temperature` with a `fahrenheit` property

            `Temperature(celsius)` stores degrees Celsius:

            - `celsius` is a property whose setter rejects values below absolute zero
              (−273.15) with `ValueError(f"below absolute zero: {value} °C")`. `__init__` must
              go through the setter.
            - `fahrenheit` is a property computed from Celsius (`c * 9 / 5 + 32`); its
              **setter** converts back and stores Celsius, so it is validated too.
            - `kelvin` is a **read-only** property (`c + 273.15`).
            - A rejected assignment leaves the old value.
            """
        ),
        code(
            '''
            ABSOLUTE_ZERO_CELSIUS = -273.15


            class Temperature:
                """A temperature stored in Celsius, readable and writable in Fahrenheit."""

                def __init__(self, celsius: float) -> None:
                    raise NotImplementedError("Lab 2.1: implement Temperature")
            '''
        ),
        md("Run the checks. Floats are rounded to two places before comparing."),
        code(
            '''
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
            '''
        ),
        md(
            """
            #### Exercise 3 — subclass-aware `User.from_dict`

            Write the `classmethod` `User.from_dict(data)`:

            - `username` and `email` are required; check them in that order and raise
              `ValueError(f"missing field: {name}")` for the first one missing.
            - Strip the username; strip and lower-case the email. `is_active` is optional
              (default `True`). Ignore unknown keys and do not modify `data`.
            - It must build an instance of **the class it is called on**, so
              `AdminUser.from_dict(...)` returns an `AdminUser`, and so does any subclass
              written later (the check defines a new `GuestUser`).

            `__init__`, `to_dict` and `AdminUser` are given.
            """
        ),
        code(
            '''
            class User:
                """A site user."""

                role = "member"

                def __init__(self, username: str, email: str, is_active: bool = True) -> None:
                    self.username = username
                    self.email = email
                    self.is_active = is_active

                @classmethod
                def from_dict(cls, data: Mapping[str, Any]) -> Self:
                    """Build a user from a mapping (username and email required)."""
                    raise NotImplementedError("Lab 2.1: implement User.from_dict")

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
            '''
        ),
        md("Run the checks."),
        code(
            '''
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
            '''
        ),
        md(
            """
            #### Exercise 4 — `ShoppingCart` and `CartItem` with `Decimal` totals

            `CartItem(sku, unit_price, quantity=1)`:

            - `unit_price` must be a `Decimal`
              (`TypeError(f"unit_price must be a Decimal, got {type_name}")`) and not negative
              (`ValueError("unit price cannot be negative")`); `quantity` must be at least 1
              (`ValueError("quantity must be at least 1")`).
            - `line_total` is a property: `unit_price * quantity`.

            `ShoppingCart()`:

            - `add(sku, unit_price, quantity=1)` returns the `CartItem`. Adding an existing SKU
              increases its quantity; a different unit price raises
              `ValueError(f"price mismatch for {sku}")`.
            - `remove(sku, quantity=None)` removes that many units (all of them when `None`, or
              when the quantity reaches zero); an unknown SKU raises `KeyError(sku)`.
            - Properties: `items` (a tuple of `CartItem`s in first-added order), `item_count`
              (total units) and `subtotal` (a `Decimal`, `Decimal("0")` when empty).
            - `total(tax_rate_percent=Decimal("18"))` returns subtotal plus tax, rounded
              `ROUND_HALF_UP` to the paisa (`PAISE`, from the setup cell).
            """
        ),
        code(
            '''
            class CartItem:
                """One line of a shopping cart."""

                def __init__(self, sku: str, unit_price: Decimal, quantity: int = 1) -> None:
                    raise NotImplementedError("Lab 2.1: implement CartItem.__init__")

                @property
                def line_total(self) -> Decimal:
                    """unit_price × quantity."""
                    raise NotImplementedError("Lab 2.1: implement CartItem.line_total")


            class ShoppingCart:
                """A cart of CartItems keyed by SKU, with exact Decimal totals."""

                def __init__(self) -> None:
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.__init__")

                def add(self, sku: str, unit_price: Decimal, quantity: int = 1) -> CartItem:
                    """Add quantity of sku."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.add")

                def remove(self, sku: str, quantity: int | None = None) -> None:
                    """Remove quantity of sku (all of it when quantity is None)."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.remove")

                @property
                def items(self) -> tuple[CartItem, ...]:
                    """The cart lines in first-added order."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.items")

                @property
                def item_count(self) -> int:
                    """Total quantity across every line."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.item_count")

                @property
                def subtotal(self) -> Decimal:
                    """Sum of line totals before tax."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.subtotal")

                def total(self, tax_rate_percent: Decimal = Decimal("18")) -> Decimal:
                    """Subtotal plus tax, rounded half-up to the paisa."""
                    raise NotImplementedError("Lab 2.1: implement ShoppingCart.total")
            '''
        ),
        md("Run the checks."),
        code(
            '''
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
                    ("remove all", lambda: after_remove("SOAP", None), [("RICE-5KG", 1, Decimal("1250.50"))]),
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
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.1."""
    return [
        md(
            """
            ### Recap — Unit 2.1

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Why classes | Bundle state with the rules that keep it valid; prefer functions, modules or dataclasses when there are no rules | `class` vs plain objects and functions |
            | `class` statement | Runs the body in a namespace, then calls `type(name, bases, namespace)` | class expression / `Object.create` |
            | `__dict__` | A class's namespace is a read-only `mappingproxy`; change it with `setattr` | `Class.prototype` |
            | Creation | `__new__` allocates, `__init__` initializes; `__new__` matters for immutable bases | `constructor` (both at once) |
            | `self` | Explicit first parameter; `obj.m(x)` is `Class.m(obj, x)` | implicit `this` |
            | Attribute lookup | instance `__dict__` → class → bases; assignment through an instance shadows | prototype chain |
            | Class-attribute trap | A mutable class attribute is shared by every instance; create it in `__init__` | class fields are per instance |
            | Bound methods | `__self__` + `__func__`; usable as callbacks without binding | `.bind(this)` |
            | `@classmethod` | Receives `cls`; use for subclass-aware alternative constructors | `static` + `this` |
            | `@staticmethod` | Receives nothing; a helper that lives with the class | `static` |
            | `@property` | Computed, read-only and validated attributes behind attribute syntax | `get` / `set` accessors |
            | Privacy | `_x` by convention, `__x` mangled to `_Class__x`; nothing is truly private | `#x` (enforced), TS `private` (compile time) |
            | Four pillars | All four exist, with lighter mechanisms: conventions, multiple inheritance, duck typing, ABCs/Protocols | Java/TS keywords |

            **Further reading**

            - [Tutorial: classes](https://docs.python.org/3/tutorial/classes.html),
              [data model: classes and instances](https://docs.python.org/3/reference/datamodel.html#classes),
              [class definitions](https://docs.python.org/3/reference/compound_stmts.html#class-definitions)
            - [`type`](https://docs.python.org/3/library/functions.html#type),
              [`vars`](https://docs.python.org/3/library/functions.html#vars),
              [`property`](https://docs.python.org/3/library/functions.html#property),
              [`classmethod`](https://docs.python.org/3/library/functions.html#classmethod),
              [`staticmethod`](https://docs.python.org/3/library/functions.html#staticmethod)
            - [Descriptor HowTo Guide](https://docs.python.org/3/howto/descriptor.html),
              [private name mangling](https://docs.python.org/3/reference/expressions.html#private-name-mangling),
              [`functools.cached_property`](https://docs.python.org/3/library/functools.html#functools.cached_property)
            - [PEP 8 — naming conventions](https://peps.python.org/pep-0008/#naming-conventions),
              [PEP 3115 — Metaclasses in Python 3](https://peps.python.org/pep-3115/),
              [PEP 526 — `ClassVar`](https://peps.python.org/pep-0526/),
              [PEP 673 — `Self`](https://peps.python.org/pep-0673/),
              [PEP 557 — Data classes](https://peps.python.org/pep-0557/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.1 and Lab 2.1."""
    return [
        *_overview_cells(),
        *_why_classes_cells(),
        *_class_statement_cells(),
        *_object_creation_cells(),
        *_attributes_cells(),
        *_methods_cells(),
        *_properties_cells(),
        *_encapsulation_cells(),
        *_js_bridge_cells(),
        *_pillars_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
