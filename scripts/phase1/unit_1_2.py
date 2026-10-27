"""Unit 1.2 — Objects, Names and Mutability."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import inspect
import math
import sys
import types
import warnings


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


print(f"{sys.version_info[:2]=}")
'''


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.2."""
    return [
        md(
            """
            ## Unit 1.2 — Objects, Names and Mutability

            **Objectives**

            - Describe every value as an object with an identity, a type and a value.
            - Explain variables as names bound to objects in a namespace dict.
            - Predict when a function call changes the caller's data.
            - Classify built-in types as mutable or immutable, and use `is` vs `==` correctly.
            - Explain why names have no type but objects do.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | Primitives (`number`, `string`) vs objects | Everything is an object | `int` and `str` are objects too, just immutable ones |
            | `let x = obj` copies a reference | `x = obj` binds a name | Same idea, but it applies to *every* value |
            | `===` | `==` (value) and `is` (identity) | `is` on numbers or strings depends on caching; never use it for that |
            | `Object.is(a, b)` | `a is b` | `is` compares identity, not value |
            | `typeof x` | `type(x)` / `isinstance(x, T)` | `isinstance` respects subclasses |
            | `delete obj.key` | `del name` | `del` unbinds a name; the object lives on while referenced |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        # 1.2.1 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.1 Everything is an object

            Every object has three things:

            | Property | How to read it | Can it change? |
            | --- | --- | --- |
            | **Identity** | `id(obj)` (CPython: the memory address) | Never, for the object's lifetime |
            | **Type** | `type(obj)` | Never (in practice) |
            | **Value** | the object itself, `repr(obj)` | Only for mutable types |

            > **Note:** `id()` values differ on every run. The demos compare ids; they never rely on
            > the number itself.
            """
        ),
        code(
            """
            price_in_rupees = 499
            cart_items = ["pen", "notebook"]
            for value in (price_in_rupees, "Asha", cart_items, 3.5, None):
                print(f"type={type(value).__name__:<8} value={value!r:<20} has an id: {id(value) > 0}")
            """
        ),
        md(
            """
            Types, functions, modules and classes are objects too: you can put them in a list, pass
            them to functions and give them attributes. Even `int` is an object, whose type is
            `type`.
            """
        ),
        code(
            '''
            def apply_discount(amount: float) -> float:
                """Return the amount with a 10% discount."""
                return amount * 0.9


            first_class_values = [int, apply_discount, math, type, len]
            for value in first_class_values:
                print(f"{getattr(value, '__name__', value)!s:<16} is a {type(value).__name__}")

            print(f"{type(int) is type=}, {type(type) is type=}")
            print(f"{inspect.isclass(int)=}, {inspect.isfunction(apply_discount)=}, {inspect.ismodule(math)=}")
            apply_discount.author = "Asha"  # functions accept new attributes like any object
            print(f"{apply_discount.author=}")
            '''
        ),
        # 1.2.2 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.2 Names and binding

            A variable is a **name**: a key in a namespace dict, bound to an object. At module level
            (and in a notebook) that dict is `globals()`. Writing to the dict is the same as
            assigning a variable.
            """
        ),
        code(
            """
            delivery_fee = 40
            module_namespace = globals()
            print(f"{type(module_namespace).__name__=}")
            print(f"{module_namespace['delivery_fee']=}")

            module_namespace["service_fee"] = 15  # same effect as: service_fee = 15
            print(f"{service_fee=}")  # noqa: F821  (created through the dict, invisible to linters)
            """
        ),
        md(
            """
            **Assignment never copies.** `b = a` binds a second name to the *same* object. If the
            object is mutable, a change through one name is visible through the other.

            ```mermaid
            flowchart LR
                subgraph names ["globals()"]
                    morning["morning_orders"]
                    alias["evening_orders"]
                end
                list_object["list object<br/>['idli', 'dosa', 'vada']"]
                morning --> list_object
                alias --> list_object
            ```

            <details><summary>ASCII fallback (Python Tutor style)</summary>

            ```text
            Frames            Objects
            +----------------+
            | morning_orders | ----+
            | evening_orders | ----+--> list ['idli', 'dosa', 'vada']
            +----------------+
            ```

            </details>
            """
        ),
        code(
            """
            morning_orders = ["idli", "dosa"]
            evening_orders = morning_orders  # a second name, not a second list
            evening_orders.append("vada")
            print(f"{morning_orders=}")
            print(f"{evening_orders is morning_orders=}")
            """
        ),
        md(
            """
            **`del` removes a name, not the object.** The object survives as long as something
            still refers to it. `sys.getrefcount` counts the references (it reports one extra for
            its own argument). CPython frees the object when the count reaches zero.
            """
        ),
        code(
            """
            reference_count_before = sys.getrefcount(morning_orders)
            del morning_orders
            print(f"{'morning_orders' in globals()=}")
            print(f"{evening_orders=}  (the list is still alive)")
            print(f"{sys.getrefcount(evening_orders) == reference_count_before - 1=}")
            try:
                print(morning_orders)  # noqa: F821
            except NameError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        # 1.2.3 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.3 Call by object reference

            Calling a function binds each parameter name to the **same object** the caller passed
            (sometimes called *call by sharing*). Two consequences:

            | Inside the function | Effect on the caller |
            | --- | --- |
            | **Mutate** the object (`items.append(...)`) | Visible: it is the same object |
            | **Rebind** the parameter (`items = [...]`) | Invisible: only the local name moved |
            """
        ),
        code(
            '''
            def add_free_gift(order_items: list[str]) -> None:
                """Mutate the caller's list by appending a gift."""
                order_items.append("free sticker")


            def replace_order(order_items: list[str]) -> None:
                """Rebind the local name only; the caller's list is untouched."""
                order_items = ["something else"]
                print(f"  inside replace_order: {order_items=}")


            customer_order = ["tea"]
            add_free_gift(customer_order)
            print(f"after add_free_gift: {customer_order=}")
            replace_order(customer_order)
            print(f"after replace_order: {customer_order=}")
            '''
        ),
        md(
            """
            The same rule applies to immutable arguments: `count += 1` inside a function rebinds the
            local name to a new `int`, so the caller sees no change. Return the new value instead.

            > **JS bridge:** Python has **no primitives**. In JS, numbers and strings are passed by
            > value and objects by reference-copy. In Python *everything* is passed the same way;
            > `int` and `str` only *look* like they are passed by value because they cannot be
            > mutated.
            """
        ),
        code(
            '''
            def increment(counter: int) -> int:
                """Return counter + 1; rebinding the parameter does not touch the caller."""
                counter += 1
                return counter


            visit_count = 10
            new_visit_count = increment(visit_count)
            print(f"{visit_count=}, {new_visit_count=}")
            '''
        ),
        # 1.2.4 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.4 Mutable vs immutable types

            | Immutable (value fixed at creation) | Mutable (value can change in place) |
            | --- | --- |
            | `int`, `float`, `complex`, `bool` | `list` |
            | `decimal.Decimal`, `fractions.Fraction` | `dict` |
            | `str` | `set` |
            | `bytes` | `bytearray` |
            | `tuple` (its items may be mutable) | `memoryview` over a writable buffer |
            | `frozenset` | `collections.deque`, `array.array` |
            | `frozendict` (new in 3.15) | instances of most user-defined classes |
            | `range`, `NoneType`, functions' code objects | `types.SimpleNamespace` |

            "Changing" an immutable object really creates a **new** object and rebinds the name.
            Watch the identity across `+=` (comparing ids, never printing them):
            """
        ),
        code(
            """
            stock_count = 1_000
            id_before = id(stock_count)
            stock_count += 1
            print(f"int:  same object after += ? {id(stock_count) == id_before}")

            greeting_text = "Namaste"
            id_before = id(greeting_text)
            greeting_text += ", Asha"
            print(f"str:  same object after += ? {id(greeting_text) == id_before}")

            basket = ["rice"]
            id_before = id(basket)
            basket += ["dal"]  # list += extends in place
            print(f"list: same object after += ? {id(basket) == id_before}")
            """
        ),
        md(
            """
            The rule of thumb: an immutable type has no method that modifies it. `str.upper()`
            returns a new string; `list.sort()` changes the list and returns `None`. Trying to
            assign into an immutable object raises `TypeError`.
            """
        ),
        code(
            """
            coordinates = (12.97, 77.59)
            try:
                coordinates[0] = 13.0
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")

            city = "bengaluru"
            print(f"{city.upper()=}, {city=}  (unchanged)")
            print(f"{basket.sort()=}  (sorted in place, returns None)")
            """
        ),
        # 1.2.5 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.5 Identity vs equality

            | Operator | Question | Implemented by |
            | --- | --- | --- |
            | `a == b` | Do they have equal **values**? | `a.__eq__(b)`, which each type defines |
            | `a is b` | Are they the **same object**? | Identity comparison; cannot be overridden |

            Use `is` only for singletons: `None`, `True`, `False`, `...`, and sentinel objects you
            create yourself. Use `==` for everything else.
            """
        ),
        code(
            '''
            class Price:
                """An amount in paise that compares by value."""

                def __init__(self, paise: int) -> None:
                    self.paise = paise

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, Price):
                        return NotImplemented
                    return self.paise == other.paise


            first_price = Price(49_900)
            second_price = Price(49_900)
            print(f"{first_price == second_price=}  (__eq__ compares paise)")
            print(f"{first_price is second_price=}  (two distinct objects)")
            first_list, second_list = [1, 2], [1, 2]
            print(f"{first_list == second_list=}, {first_list is second_list=}")
            '''
        ),
        md(
            """
            **Small-integer cache.** CPython pre-creates small `int` objects and reuses them, so two
            names bound to the same small value can be the *same object*. The range changed:

            | Python | Cached range |
            | --- | --- |
            | up to 3.14 | `-5` … `256` |
            | **3.15** (*changed in 3.15*) | `-5` … `1024` |

            The cell builds numbers at run time with `int("…")`. Literals in one cell would be
            merged into a single constant by the compiler and hide the effect. This is an
            implementation detail, which is exactly why you must not use `is` for numbers.
            """
        ),
        code(
            """
            for number_text in ["256", "257", "1024", "1025"]:
                first_number, second_number = int(number_text), int(number_text)
                is_same_object = first_number is second_number
                print(f"{number_text:>5}: equal={first_number == second_number}, same object={is_same_object}")
            if sys.version_info < (3, 15):
                print("Note: on this Python the cache ends at 256, so 1024 is not shared")
            """
        ),
        md(
            """
            **String interning.** CPython also shares some strings: identifier-like literals and
            names are *interned* automatically. Strings built at run time usually are not.
            `sys.intern` interns one on request, which can save memory and makes later comparisons
            identity checks (used inside dicts of attribute names).
            """
        ),
        code(
            """
            built_status = "".join(["sh", "ipped"])
            literal_status = "shipped"
            print(f"{built_status == literal_status=}, {built_status is literal_status=}")

            interned_status = sys.intern(built_status)
            print(f"{interned_status is literal_status=}  (sys.intern returned the shared copy)")
            """
        ),
        md(
            """
            Because results like these vary by version and context, the compiler warns when you use
            `is` with a literal. The cell compiles such code and captures the **`SyntaxWarning`**
            (new in 3.8) instead of letting it print.
            """
        ),
        code(
            """
            suspicious_source = "order_count = 5\\nprint(order_count is 5)"
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                compile(suspicious_source, "<demo>", "exec")
            for caught_warning in caught_warnings:
                print(f"{caught_warning.category.__name__}: {caught_warning.message}")
            """
        ),
        # 1.2.6 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.2.6 Dynamic typing

            **Names have no types; objects do.** One name can be rebound to objects of different
            types. Type hints (`price: int`) document intent and help tools such as pyright, but
            the interpreter does not enforce them (Phase 4).
            """
        ),
        code(
            """
            shipment_reference = 1042
            print(f"{type(shipment_reference).__name__=}")
            shipment_reference = "SHIP-1042"
            print(f"{type(shipment_reference).__name__=}")

            hinted_quantity: int = "three"  # legal at run time: hints are not checked
            print(f"{hinted_quantity=}, {type(hinted_quantity).__name__=}")
            """
        ),
        md(
            """
            **`type()` vs `isinstance()`.** `type(x) is T` matches one exact class.
            `isinstance(x, T)` also accepts subclasses, and takes a tuple (or a `X | Y` union) of
            types. Prefer `isinstance` for checks.
            """
        ),
        code(
            '''
            class DiscountedPrice(Price):
                """A Price subclass."""


            sale_price = DiscountedPrice(39_900)
            print(f"{type(sale_price) is Price=}")
            print(f"{isinstance(sale_price, Price)=}")
            print(f"{isinstance(3.5, int | float)=}")
            print(f"{isinstance(True, int)=}  (bool is a subclass of int; see 1.3.6)")
            '''
        ),
        md(
            """
            **Duck typing preview.** Python code usually does not check types at all: it calls the
            method it needs and lets anything that has it work ("if it walks like a duck…").
            Phase 2 formalises this with protocols.
            """
        ),
        code(
            '''
            class PaperReceipt:
                """A receipt that is printed."""

                def render(self) -> str:
                    """Return a description of the receipt."""
                    return "Printed receipt"


            class EmailReceipt:
                """A receipt that is emailed; unrelated to PaperReceipt."""

                def render(self) -> str:
                    """Return a description of the receipt."""
                    return "Emailed receipt"


            def send_receipt(receipt: PaperReceipt | EmailReceipt) -> None:
                """Works with any object that has a render() method."""
                print(receipt.render())


            ad_hoc_receipt = types.SimpleNamespace(render=lambda: "Ad-hoc receipt")
            for receipt in (PaperReceipt(), EmailReceipt(), ad_hoc_receipt):
                send_receipt(receipt)
            '''
        ),
        # Under the hood + predict ----------------------------------------------------------------
        md(
            """
            #### Under the hood: names live in `__dict__`, objects carry headers

            A module's globals are literally its `__dict__`, and an instance's attributes are in its
            own `__dict__`. Every object also carries a header (reference count and type pointer),
            which is why even `0` costs bytes. `show_size` (from the shared setup) prints the
            shallow size.
            """
        ),
        code(
            """
            print(f"{globals() is sys.modules['__main__'].__dict__=}")
            print(f"{vars(first_price)=}")
            show_size("small int 0", 0)
            show_size("None", None)
            show_size("empty list", [])
            """
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            shopping_list = ["milk"]
            other_list = shopping_list
            other_list = other_list + ["bread"]
            print(shopping_list)
            """,
            answer="""
            `['milk']`. `other_list + [...]` builds a **new** list and rebinds `other_list` to it;
            `shopping_list` still points at the original. Compare `basket += [...]` in 1.2.4,
            which extends the list in place.
            """,
            proof="""
            shopping_list = ["milk"]
            other_list = shopping_list
            other_list = other_list + ["bread"]
            print(shopping_list)
            """,
        ),
        *predict_cells(
            snippet="""
            def reset(scores):
                scores.clear()
                scores = [100]

            team_scores = [7, 9]
            reset(team_scores)
            print(team_scores)
            """,
            answer="""
            `[]`. `clear()` mutates the caller's list; the rebinding on the next line only moves
            the local name.
            """,
            proof='''
            def reset(scores: list[int]) -> None:
                """Clear the caller's list, then rebind the local name."""
                scores.clear()
                scores = [100]


            team_scores = [7, 9]
            reset(team_scores)
            print(team_scores)
            ''',
        ),
        md(
            """
            ### Recap — Unit 1.2

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Everything is an object | Identity, type and value; classes, functions, modules too | Objects, but JS also has primitives |
            | Names and binding | A variable is a key in a namespace dict bound to an object | Variable holds a reference |
            | Assignment | Never copies; two names can share one object | Same for objects |
            | `del` | Removes a name; the object dies when unreferenced | `delete` removes a property |
            | Call by object reference | Mutation is visible to the caller, rebinding is not | Same for objects; primitives copy |
            | Mutable vs immutable | `list`/`dict`/`set` change in place; `int`/`str`/`tuple` never do | Objects vs primitives |
            | `is` vs `==` | `is` for singletons only; small-int cache is `-5..1024` in 3.15 | `Object.is` vs `===` |
            | Dynamic typing | Names untyped, objects typed; prefer `isinstance` and duck typing | `typeof`, `instanceof` |

            **Further reading**

            - [Data model: objects, values and types](https://docs.python.org/3/reference/datamodel.html#objects-values-and-types)
            - [Naming and binding](https://docs.python.org/3/reference/executionmodel.html#naming-and-binding)
            - [Programming FAQ: how do I write a function with output parameters?](https://docs.python.org/3/faq/programming.html#how-do-i-write-a-function-with-output-parameters-call-by-reference)
            - [`sys.intern`](https://docs.python.org/3/library/sys.html#sys.intern),
              [`isinstance`](https://docs.python.org/3/library/functions.html#isinstance),
              [`id`](https://docs.python.org/3/library/functions.html#id)
            - [PEP 8 — comparisons to singletons](https://peps.python.org/pep-0008/#programming-recommendations)
            """
        ),
    ]
