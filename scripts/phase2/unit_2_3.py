"""Unit 2.3 — Abstractions: ABCs, collections.abc and Protocols (with Lab 2.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import functools
import importlib.util
import inspect
import io
import json
import os
import shutil
import sys
import timeit
import typing
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import (
    Callable,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
    Set,
    Sized,
)
from decimal import Decimal
from math import pi  # noqa: F401 (Lab 2.3)
from typing import Any, NamedTuple, Protocol, runtime_checkable


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
            ## Unit 2.3 — Abstractions: ABCs, `collections.abc` and Protocols

            **Objectives**

            - Define abstract base classes with abstract methods and properties, and use the
              template-method pattern.
            - Implement a few methods of a `collections.abc` class and get the rest for free;
              use `register` and `__subclasshook__`.
            - Describe interfaces structurally with `typing.Protocol`, as in TypeScript, and
              know what `@runtime_checkable` can and cannot check.
            - Choose between an ABC and a Protocol.
            - Write polymorphic code with duck typing and EAFP instead of type checks.

            **JS / TS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | TS `abstract class` / `abstract method()` | `class X(ABC)` + `@abstractmethod` | Checked at **run time**, when you instantiate, not at compile time |
            | TS `interface` (structural) | `typing.Protocol` | Checked by a type checker (mypy, pyright); ignored at run time by default |
            | TS `implements Shape` | optional: `class Circle(Shape)` with a Protocol or ABC base | Not needed for Protocols: matching the shape is enough |
            | `x instanceof SomeInterface` (impossible: interfaces are erased) | `isinstance(x, Proto)` with `@runtime_checkable` | Only checks that the **names** exist |
            | `Symbol.hasInstance` | `__subclasshook__` / `ABC.register` | Customizes `isinstance` / `issubclass` |
            | `Symbol.iterator` protocol | `collections.abc.Iterable` (`__iter__`) | Built-in ABCs recognize the protocol structurally |
            | `ReadonlyMap<K, V>` / `Map<K, V>` | `Mapping[K, V]` / `MutableMapping[K, V]` | Implement 3 (or 5) methods, inherit the rest |
            | `typeof x.close === "function"` | `try: x.close()` / `except AttributeError:` | EAFP over checks (2.3.4) |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _abc_cells() -> list[NotebookNode]:
    """2.3.1 Abstract base classes."""
    return [
        md(
            """
            ### 2.3.1 Abstract base classes

            An **abstract base class** (ABC) declares methods that subclasses **must** provide.
            Inherit from `abc.ABC` and decorate those methods with `@abstractmethod`. Python then
            refuses to instantiate the ABC itself, or any subclass that leaves an abstract method
            unimplemented. An ABC can also have ordinary (concrete) methods built on top of the
            abstract ones; here `exists()` works for every storage backend.
            """
        ),
        code(
            '''
            class Storage(ABC):
                """Where uploaded files go. Subclasses decide how."""

                @abstractmethod
                def save(self, name: str, data: bytes) -> str:
                    """Store data and return its location."""

                @abstractmethod
                def load(self, location: str) -> bytes:
                    """Return the stored bytes, or raise KeyError."""

                def exists(self, location: str) -> bool:
                    """Concrete method built on the abstract load()."""
                    try:
                        self.load(location)
                    except KeyError:
                        return False
                    return True
            '''
        ),
        md(
            """
            The error comes at **instantiation time**: defining an incomplete subclass is fine,
            creating an instance of it is not. The message names every missing method. A
            complete subclass works and inherits `exists()`.
            """
        ),
        code(
            '''
            class HalfDoneStorage(Storage):
                """Implements save() but forgets load()."""

                def save(self, name: str, data: bytes) -> str:
                    return name


            class MemoryStorage(Storage):
                """Keeps files in a dict."""

                def __init__(self) -> None:
                    self._files: dict[str, bytes] = {}

                def save(self, name: str, data: bytes) -> str:
                    location = f"mem://{name}"
                    self._files[location] = data
                    return location

                def load(self, location: str) -> bytes:
                    return self._files[location]


            print(raised_message(Storage))
            print(raised_message(HalfDoneStorage))
            memory_storage = MemoryStorage()
            invoice_location = memory_storage.save("invoice.pdf", b"%PDF-1.7")
            print(
                f"{invoice_location=}, {memory_storage.exists(invoice_location)=}, {memory_storage.exists('mem://x')=}"
            )
            '''
        ),
        md(
            """
            #### Under the hood: `ABCMeta` and `__abstractmethods__`

            `ABC` is just a convenience base whose metaclass is **`ABCMeta`**. When the class is
            created, `ABCMeta` collects every name still marked abstract into the frozenset
            `__abstractmethods__`; `object.__new__` refuses to instantiate a class whose set is
            not empty. `inspect.isabstract` reads the same information.
            """
        ),
        code(
            """
            print(f"{type(Storage)=}")
            print(f"{sorted(Storage.__abstractmethods__)=}")
            print(f"{sorted(HalfDoneStorage.__abstractmethods__)=}")
            print(f"{MemoryStorage.__abstractmethods__=}")
            print(f"{inspect.isabstract(Storage)=}, {inspect.isabstract(MemoryStorage)=}")


            class ExplicitMetaclass(metaclass=ABCMeta):  # the same as inheriting from ABC
                @abstractmethod
                def run(self) -> None: ...


            print(f"{inspect.isabstract(ExplicitMetaclass)=}")
            """
        ),
        md(
            """
            Unlike Java interfaces, an abstract method **can have a body**. Subclasses must still
            override it, but they can call the shared part with `super()`.
            """
        ),
        code(
            '''
            class Uploader(ABC):
                @abstractmethod
                def validate(self, file_name: str) -> list[str]:
                    """Checks every uploader shares; subclasses extend them."""
                    return [] if file_name else ["empty file name"]


            class ImageUploader(Uploader):
                def validate(self, file_name: str) -> list[str]:
                    problems = super().validate(file_name)
                    if not file_name.endswith((".png", ".jpg")):
                        problems.append("not an image")
                    return problems


            print(f"{ImageUploader().validate('logo.png')=}")
            print(f"{ImageUploader().validate('')=}")
            '''
        ),
        md(
            """
            **Abstract properties and class methods.** Stack `@abstractmethod` **under**
            `@property` (or `@classmethod`), so `abstractmethod` is applied first. A subclass can
            satisfy an abstract property with a real property or simply with a class attribute
            of the same name.
            """
        ),
        code(
            '''
            class Backend(ABC):
                @property
                @abstractmethod
                def scheme(self) -> str:
                    """URL scheme this backend handles, e.g. "s3"."""

                @classmethod
                @abstractmethod
                def from_url(cls, url: str) -> Backend:
                    """Build a backend from a URL."""


            class S3Backend(Backend):
                def __init__(self, bucket: str) -> None:
                    self.bucket = bucket

                @property
                def scheme(self) -> str:
                    return "s3"

                @classmethod
                def from_url(cls, url: str) -> S3Backend:
                    return cls(url.removeprefix("s3://").split("/")[0])


            class LocalBackend(Backend):
                scheme = "file"  # a plain class attribute also satisfies the abstract property

                @classmethod
                def from_url(cls, url: str) -> LocalBackend:
                    return cls()


            print(f"{S3Backend.from_url('s3://invoices/2026/11').bucket=}, {S3Backend('x').scheme=}")
            print(f"{LocalBackend.from_url('file:///tmp').scheme=}, {sorted(Backend.__abstractmethods__)=}")
            '''
        ),
        md(
            """
            **The template-method pattern.** The base class owns the **algorithm** (a concrete
            method that calls steps in a fixed order); subclasses fill in the **steps**. Here
            `OrderImporter.run` always parses, cleans, validates and collects errors; the CSV
            and JSON importers only say how to parse and what makes a record valid. `clean` is
            an optional **hook** with a default.
            """
        ),
        code(
            '''
            class OrderImporter(ABC):
                """Template method: run() fixes the steps, subclasses implement them."""

                def run(self, raw_text: str) -> tuple[list[dict[str, Any]], list[str]]:
                    accepted: list[dict[str, Any]] = []
                    errors: list[str] = []
                    for record in self.parse(raw_text):
                        record = self.clean(record)
                        problem = self.validate(record)
                        if problem is None:
                            accepted.append(record)
                        else:
                            errors.append(problem)
                    return accepted, errors

                @abstractmethod
                def parse(self, raw_text: str) -> list[dict[str, Any]]:
                    """Turn raw text into records."""

                def clean(self, record: dict[str, Any]) -> dict[str, Any]:
                    """Optional hook: normalize a record (default: unchanged)."""
                    return record

                @abstractmethod
                def validate(self, record: dict[str, Any]) -> str | None:
                    """Return an error message, or None when the record is valid."""
            '''
        ),
        md("Two importers that only supply the steps:"),
        code(
            """
            class CsvOrderImporter(OrderImporter):
                def parse(self, raw_text: str) -> list[dict[str, Any]]:
                    rows = [line.split(",") for line in raw_text.strip().splitlines()[1:]]
                    return [{"order_id": order_id, "quantity": quantity} for order_id, quantity in rows]

                def clean(self, record: dict[str, Any]) -> dict[str, Any]:
                    return {**record, "quantity": int(record["quantity"])}

                def validate(self, record: dict[str, Any]) -> str | None:
                    if record["quantity"] > 0:
                        return None
                    return f"{record['order_id']}: quantity must be positive"


            class JsonOrderImporter(OrderImporter):
                def parse(self, raw_text: str) -> list[dict[str, Any]]:
                    return json.loads(raw_text)

                def validate(self, record: dict[str, Any]) -> str | None:
                    return None if "order_id" in record else "record without order_id"


            print(CsvOrderImporter().run("order_id,quantity\\nORD-1,2\\nORD-2,0"))
            print(JsonOrderImporter().run('[{"order_id": "ORD-3", "quantity": 1}, {"quantity": 4}]'))
            """
        ),
    ]


def _collections_abc_cells() -> list[NotebookNode]:
    """2.3.2 collections.abc."""
    return [
        md(
            """
            ### 2.3.2 `collections.abc`

            The `collections.abc` module defines ABCs for Python's container protocols. Each
            one has a few **abstract methods** you write, and **mixin methods** it implements for
            you on top of them. Inheriting also makes `isinstance(obj, Mapping)` (and so on)
            true, so code that accepts "any mapping" accepts your class.

            | ABC | You write | You get for free |
            | --- | --- | --- |
            | `Iterable` | `__iter__` | (recognized structurally, see `__subclasshook__` below) |
            | `Iterator` | `__next__` | `__iter__` (returns `self`) |
            | `Sequence` | `__getitem__`, `__len__` | `__contains__`, `__iter__`, `__reversed__`, `index`, `count` |
            | `Mapping` | `__getitem__`, `__iter__`, `__len__` | `__contains__`, `keys`, `items`, `values`, `get`, `__eq__`, `__ne__` |
            | `MutableMapping` | the `Mapping` three + `__setitem__`, `__delitem__` | the `Mapping` mixins + `pop`, `popitem`, `clear`, `update`, `setdefault` |
            | `Set` | `__contains__`, `__iter__`, `__len__` | `<=`, `<`, `==`, `!=`, `>`, `>=`, `&`, `|`, `-`, `^`, `isdisjoint` |

            > **Note:** `Set` here is `collections.abc.Set`, the abstract read-only set, not the
            > built-in `set` type.

            #### `Iterable`

            Any class with `__iter__` counts as `Iterable`, without inheriting or registering.
            A class that only has the old `__getitem__` protocol can still be iterated by
            `iter()`, but `isinstance(…, Iterable)` says `False`. To ask "can I iterate this?",
            call `iter()` and catch `TypeError` (EAFP, 2.3.4).
            """
        ),
        code(
            '''
            class Playlist:
                """Iterable by defining __iter__; no base class."""

                def __init__(self, *songs: str) -> None:
                    self._songs = list(songs)

                def __iter__(self) -> Iterator[str]:
                    return iter(self._songs)


            class LegacyPlaylist:
                """Only the old __getitem__ protocol."""

                def __getitem__(self, index: int) -> str:
                    return ["Raga Yaman", "Raga Bhairav"][index]


            print(f"{isinstance(Playlist('Raga Yaman'), Iterable)=}")
            print(f"{list(LegacyPlaylist())=}, {isinstance(LegacyPlaylist(), Iterable)=}")
            print(raised_message(lambda: iter(42)))
            '''
        ),
        md(
            """
            #### `Iterator`

            Inherit from `Iterator` and write only `__next__`; the ABC supplies the
            `__iter__` that returns `self` (1.13).
            """
        ),
        code(
            '''
            class TicketDispenser(Iterator[int]):
                """Hands out ticket numbers first..last."""

                def __init__(self, first: int, last: int) -> None:
                    self._next_number = first
                    self._last = last

                def __next__(self) -> int:
                    if self._next_number > self._last:
                        raise StopIteration
                    number = self._next_number
                    self._next_number += 1
                    return number


            dispenser = TicketDispenser(101, 104)
            print(f"{iter(dispenser) is dispenser=}, {'__iter__' in vars(TicketDispenser)=}")
            print(f"{list(dispenser)=}, {list(dispenser)=}  (exhausted)")
            '''
        ),
        md(
            """
            #### `Sequence`

            `PageRange` describes the page boundaries for paginating `total_items` results.
            It computes each page on demand instead of storing a list, writes only `__len__`
            and `__getitem__` (with negative indexes and slices), and gets `in`, iteration,
            `reversed`, `index` and `count` from `Sequence`.
            """
        ),
        code(
            '''
            class PageRange(Sequence[tuple[int, int]]):
                """(start, stop) item offsets for each page of total_items results."""

                def __init__(self, total_items: int, page_size: int) -> None:
                    self.total_items = total_items
                    self.page_size = page_size

                def __len__(self) -> int:
                    return -(-self.total_items // self.page_size)  # ceiling division

                def __getitem__(self, index: int | slice) -> Any:
                    if isinstance(index, slice):
                        return [self[position] for position in range(*index.indices(len(self)))]
                    if index < 0:
                        index += len(self)
                    if not 0 <= index < len(self):
                        raise IndexError("page out of range")
                    start = index * self.page_size
                    return start, min(start + self.page_size, self.total_items)
            '''
        ),
        md("Every line below except the first two uses a method `PageRange` never wrote."),
        code(
            """
            pages = PageRange(total_items=45, page_size=10)
            print(f"{len(pages)=}, {pages[-1]=}, {pages[1:3]=}")
            print(f"{list(pages)=}")
            print(f"{(40, 45) in pages=}, {pages.index((20, 30))=}, {pages.count((0, 10))=}")
            print(f"{list(reversed(pages))[:2]=}")
            print(f"{isinstance(pages, Sequence)=}")
            """
        ),
        md(
            """
            #### `Mapping`

            `EnvironmentConfig` exposes the environment variables that share a prefix, with the
            prefix removed and the keys lower-cased. Three methods are enough for `get`, `in`,
            `keys`, `items`, `values`, `==` and `dict(...)` to work. The real `os.environ` is
            itself a `MutableMapping`; the demo uses a fake environment so the output is the
            same on every machine.
            """
        ),
        code(
            '''
            class EnvironmentConfig(Mapping[str, str]):
                """Settings from prefixed environment variables, e.g. APP_PORT -> "port"."""

                def __init__(self, environ: Mapping[str, str], prefix: str) -> None:
                    self._values = {
                        name.removeprefix(prefix).lower(): value
                        for name, value in environ.items()
                        if name.startswith(prefix)
                    }

                def __getitem__(self, key: str) -> str:
                    return self._values[key]

                def __iter__(self) -> Iterator[str]:
                    return iter(self._values)

                def __len__(self) -> int:
                    return len(self._values)


            fake_environ = {"APP_DEBUG": "1", "APP_PORT": "8000", "HOME": "/home/asha"}
            app_config = EnvironmentConfig(fake_environ, prefix="APP_")
            print(f"{dict(app_config)=}, {app_config.get('port')=}, {app_config.get('host', 'localhost')=}")
            print(f"{'debug' in app_config=}, {app_config == {'debug': '1', 'port': '8000'}=}")
            print(f"{isinstance(os.environ, MutableMapping)=}")
            '''
        ),
        md(
            """
            #### `MutableMapping`

            HTTP header names are case-insensitive. `CaseInsensitiveDict` stores each entry
            under the lower-cased key but remembers the original spelling. Five methods give it
            `update`, `setdefault`, `pop`, `popitem` and `clear` too; the constructor itself
            uses the free `update`.
            """
        ),
        code(
            '''
            class CaseInsensitiveDict(MutableMapping[str, str]):
                """A str -> str mapping whose keys ignore case (like HTTP headers)."""

                def __init__(self, initial: Mapping[str, str] | None = None) -> None:
                    self._store: dict[str, tuple[str, str]] = {}
                    if initial:
                        self.update(initial)  # update() is a free mixin method

                def __setitem__(self, key: str, value: str) -> None:
                    self._store[key.lower()] = (key, value)

                def __getitem__(self, key: str) -> str:
                    return self._store[key.lower()][1]

                def __delitem__(self, key: str) -> None:
                    del self._store[key.lower()]

                def __iter__(self) -> Iterator[str]:
                    return (original_key for original_key, _ in self._store.values())

                def __len__(self) -> int:
                    return len(self._store)


            headers = CaseInsensitiveDict({"Content-Type": "application/json"})
            headers.setdefault("X-Request-ID", "req-42")
            print(f"{headers['CONTENT-TYPE']=}, {'x-request-id' in headers=}, {list(headers)=}")
            print(f"{headers.pop('content-type')=}, {dict(headers)=}")
            '''
        ),
        md(
            """
            #### `Set`

            A read-only set of permissions. Three methods give it every comparison and set
            operator. Operators build their result with the class method `_from_iterable`,
            which by default calls `cls(iterable)`; that works here because the constructor
            accepts an iterable (otherwise you would override `_from_iterable`).
            """
        ),
        code(
            '''
            class PermissionSet(Set[str]):
                """An immutable set of permission names."""

                def __init__(self, permissions: Iterable[str] = ()) -> None:
                    self._permissions = frozenset(permissions)

                def __contains__(self, permission: object) -> bool:
                    return permission in self._permissions

                def __iter__(self) -> Iterator[str]:
                    return iter(sorted(self._permissions))

                def __len__(self) -> int:
                    return len(self._permissions)


            editor = PermissionSet({"read", "write"})
            admin = PermissionSet({"read", "write", "delete"})
            print(f"{editor <= admin=}, {editor < admin=}, {editor == PermissionSet(['write', 'read'])=}")
            print(f"{list(admin - editor)=}, {list(editor | {'comment'})=}, {type(admin & editor).__name__=}")
            print(f"{editor.isdisjoint({'delete'})=}")
            '''
        ),
        md(
            """
            #### Mixin methods for free, counted

            `free_methods` lists what each ABC implements on top of its abstract methods, by
            walking the ABC's MRO (an `inspect`-style look at the class dictionaries).
            """
        ),
        code(
            '''
            def free_methods(abc_class: type) -> list[str]:
                """Callable members an ABC defines on top of its abstract methods."""
                found: set[str] = set()
                for klass in abc_class.__mro__[:-1]:  # skip object
                    for name, value in vars(klass).items():
                        is_public_or_dunder = not name.startswith("_") or name.endswith("__")
                        if (
                            callable(value)
                            and is_public_or_dunder
                            and name not in abc_class.__abstractmethods__
                        ):
                            found.add(name)
                return sorted(found - {"__subclasshook__", "__class_getitem__", "__init_subclass__"})


            for abc_class in [Iterator, Sequence, Mapping, MutableMapping, Set]:
                print(f"{abc_class.__name__:<15} write {sorted(abc_class.__abstractmethods__)}")
                print(f"{'':<15} free  {free_methods(abc_class)}")
            '''
        ),
        md(
            """
            #### `register`: virtual subclasses

            `SomeABC.register(cls)` declares that `cls` implements the ABC **without
            inheriting**. `isinstance` and `issubclass` then return `True`, but the class gets
            **no mixin methods** and the ABC is **not** in its MRO. Python also does **no
            checking**: registering is a promise you make. The built-ins are wired up this way:
            `list` is a registered `MutableSequence`.
            """
        ),
        code(
            '''
            class LegacyRecordSet:
                """An old class we cannot change: it has __len__ and __getitem__."""

                def __init__(self, records: list[str]) -> None:
                    self._records = records

                def __len__(self) -> int:
                    return len(self._records)

                def __getitem__(self, index: int) -> str:
                    return self._records[index]


            Sequence.register(LegacyRecordSet)
            legacy_records = LegacyRecordSet(["r1", "r2"])
            print(f"{isinstance(legacy_records, Sequence)=}, {Sequence in LegacyRecordSet.__mro__=}")
            print(f"{hasattr(legacy_records, 'index')=}  (no mixin methods for virtual subclasses)")
            print(f"{issubclass(list, MutableSequence)=}, {MutableSequence in list.__mro__=}")
            '''
        ),
        md(
            """
            #### `__subclasshook__`: structural checks

            An ABC can decide membership by **inspecting the candidate class**. `Iterable`,
            `Sized`, `Hashable` and friends do exactly this: their `__subclasshook__` looks for
            the method in the class's MRO. Returning `NotImplemented` means "no opinion", so
            normal inheritance and registration still apply. A list is not `Hashable`, because
            `list` sets `__hash__ = None`, and the hook treats a `None` method as missing.
            """
        ),
        code(
            """
            print(inspect.getsource(Sized.__subclasshook__))
            print(f"{isinstance(PageRange(10, 5), Sized)=}, {isinstance([], Hashable)=}")
            """
        ),
        md(
            """
            Your own ABC can do the same. `SupportsToJson` accepts any class that defines a
            callable `to_json`, anywhere in its MRO, without inheritance or registration
            (`JsonSerializableMixin` from 2.2.4 would qualify).
            """
        ),
        code(
            '''
            class SupportsToJson(ABC):  # noqa: B024 (membership comes from __subclasshook__)
                """Any class with a callable to_json() is a virtual subclass."""

                @classmethod
                def __subclasshook__(cls, candidate: type) -> Any:
                    if cls is SupportsToJson:
                        for klass in candidate.__mro__:
                            if "to_json" in vars(klass):
                                return callable(vars(klass)["to_json"])
                    return NotImplemented


            class InvoiceRecord:
                def to_json(self) -> str:
                    return '{"invoice": "INV-9"}'


            class PlainRecord:
                pass


            print(f"{isinstance(InvoiceRecord(), SupportsToJson)=}")
            print(f"{isinstance(PlainRecord(), SupportsToJson)=}, {issubclass(dict, SupportsToJson)=}")
            '''
        ),
    ]


def _protocol_cells() -> list[NotebookNode]:
    """2.3.3 Protocols (PEP 544)."""
    return [
        md(
            """
            ### 2.3.3 Protocols (PEP 544)

            An ABC is **nominal**: a class belongs because it inherits (or is registered).
            A **Protocol** is **structural**, exactly like a TypeScript interface: any class
            with matching methods satisfies it, with no inheritance and no registration.

            ```typescript
            interface MessageChannel {
              send(recipient: string, message: string): boolean;
            }
            function broadcast(channel: MessageChannel, recipients: string[], message: string) { … }
            broadcast({ send: (recipient, message) => true }, ["asha"], "hi");  // any matching shape
            ```

            The Python version: `MessageChannel` describes the shape, and two unrelated classes
            match it.
            """
        ),
        code(
            '''
            class MessageChannel(Protocol):
                """Anything that can send a message and report success."""

                def send(self, recipient: str, message: str) -> bool: ...


            def broadcast(channel: MessageChannel, recipients: list[str], message: str) -> int:
                """Send to every recipient; return how many succeeded."""
                return sum(channel.send(recipient, message) for recipient in recipients)
            '''
        ),
        md(
            """
            Two channels that never mention `MessageChannel`. They match because they have a
            `send(recipient, message) -> bool` method, and `broadcast` accepts both.
            """
        ),
        code(
            '''
            class ConsoleChannel:
                """No base class, no registration: it just has send()."""

                def __init__(self) -> None:
                    self.sent: list[str] = []

                def send(self, recipient: str, message: str) -> bool:
                    self.sent.append(f"{recipient}: {message}")
                    return True


            class PushChannel:
                """Only reaches users with a registered device."""

                def __init__(self, device_owners: set[str]) -> None:
                    self.device_owners = device_owners

                def send(self, recipient: str, message: str) -> bool:
                    return recipient in self.device_owners


            console = ConsoleChannel()
            print(f"{broadcast(console, ['asha', 'ravi'], 'Sale starts now')=}, {console.sent=}")
            print(f"{broadcast(PushChannel({'ravi'}), ['asha', 'ravi'], 'Sale starts now')=}")
            '''
        ),
        md(
            """
            **At run time a Protocol does nothing.** Annotations are not enforced: passing a
            string fails only when `send` is called. And a plain Protocol cannot be used with
            `isinstance` at all; that needs `@runtime_checkable` (below).

            The checking happens in a **type checker** (mypy or pyright), before the code runs.
            mypy would report the bad call as:

            ```text
            error: Argument 1 to "broadcast" has incompatible type "str"; expected "MessageChannel"  [arg-type]
            ```
            """
        ),
        code(
            """
            print(raised_message(lambda: broadcast("not a channel", ["asha"], "hi")))  # type: ignore[arg-type]
            print(raised_message(lambda: isinstance(console, MessageChannel)))
            """
        ),
        md(
            """
            The type checkers are Phase 4 tools and are not installed yet, so this cell only
            reports whether one is available.
            """
        ),
        code(
            """
            for checker_module, checker_command in [("mypy", "mypy"), ("pyright", "pyright")]:
                installed = importlib.util.find_spec(checker_module) or shutil.which(checker_command)
                status = "available" if installed else "not installed yet (Phase 4): skipping"
                print(f"{checker_module}: {status}")
            """
        ),
        md(
            """
            **Inspecting a Protocol.** `typing.get_protocol_members` and `typing.is_protocol`
            (*New in 3.13*) list the members a class must have. You *may* inherit from a
            Protocol explicitly, like TypeScript's `implements`; the class then also inherits
            any default method bodies. A Protocol itself cannot be instantiated.
            """
        ),
        code(
            '''
            class LoggedChannel(MessageChannel):
                """Explicitly declares that it implements MessageChannel."""

                def send(self, recipient: str, message: str) -> bool:
                    return bool(recipient)


            if sys.version_info >= (3, 13):
                print(f"{typing.get_protocol_members(MessageChannel)=}")
                print(f"{typing.is_protocol(MessageChannel)=}, {typing.is_protocol(LoggedChannel)=}")
            else:
                print("get_protocol_members / is_protocol need Python 3.13+")
            print(f"{LoggedChannel().send('asha', 'hi')=}")
            print(raised_message(MessageChannel))
            '''
        ),
        md(
            """
            Protocols can describe **attributes** as well as methods, and they combine with
            generics. `cheapest` accepts any items that support `<`, so it works for `Decimal`,
            `str` and anything else comparable, while a type checker still rejects items that
            cannot be compared. (PEP 695 syntax `[T: Bound]`, 3.12+.)
            """
        ),
        code(
            '''
            class SupportsLessThan(Protocol):
                def __lt__(self, other: Any, /) -> bool: ...


            class Named(Protocol):
                name: str  # an attribute member


            def cheapest[T: SupportsLessThan](items: Iterable[T]) -> T:
                """The smallest item; T can be any comparable type."""
                return min(items)


            def greeting(thing: Named) -> str:
                return f"Hello, {thing.name}"


            class Shop:
                def __init__(self, name: str) -> None:
                    self.name = name


            print(f"{cheapest([Decimal('49.50'), Decimal('12.00'), Decimal('120')])=}")
            print(f"{cheapest(['tea', 'coffee', 'soap'])=}")
            print(greeting(Shop("Kirana Corner")))
            '''
        ),
        md(
            """
            #### `@runtime_checkable` and its limits

            Decorating a Protocol with `@runtime_checkable` makes `isinstance` work. It checks
            only that every member **name exists** on the object:
            """
        ),
        code(
            """
            @runtime_checkable
            class Flushable(Protocol):
                def flush(self) -> None: ...


            print(f"{isinstance(io.StringIO(), Flushable)=}, {isinstance(sys.stdout, Flushable)=}")
            print(f"{isinstance(42, Flushable)=}, {issubclass(io.BytesIO, Flushable)=}")
            """
        ),
        md(
            """
            **Limit 1: names, not signatures.** The check ignores parameters and return types,
            and does not even require the member to be callable. Only a member explicitly set
            to `None` counts as missing.
            """
        ),
        code(
            """
            class WrongSignature:
                def flush(self, force: bool, level: int) -> str:
                    return "nothing like the protocol"


            class NotEvenAMethod:
                flush = "yes"


            class ExplicitlyNone:
                flush = None


            for candidate in [WrongSignature, NotEvenAMethod, ExplicitlyNone]:
                print(f"{candidate.__name__:<15} isinstance -> {isinstance(candidate(), Flushable)}")
            """
        ),
        md(
            """
            **Limit 2: no `issubclass` with attribute members.** Without an instance Python
            cannot know whether an attribute will exist, so Protocols with data members only
            support `isinstance`.

            **Limit 3: properties are not run.** Since 3.12 the check uses
            `inspect.getattr_static`, so it never executes a property or `__getattr__`; a
            property that would raise still counts as present.
            """
        ),
        code(
            """
            @runtime_checkable
            class HasName(Protocol):
                name: str


            class LazyRecord:
                @property
                def name(self) -> str:
                    raise RuntimeError("database unavailable")


            print(f"{isinstance(LazyRecord(), HasName)=}  (the property was never called)")
            print(raised_message(lambda: issubclass(LazyRecord, HasName)))
            """
        ),
        md(
            """
            **Limit 4: speed.** A runtime Protocol check looks up every member on every call. It
            is slower than an ABC check (whose result is cached per class) and several times
            slower than a plain `hasattr`. Avoid it in hot loops.

            > **Note:** timings vary by machine and Python version; compare the ratios.
            """
        ),
        code(
            """
            buffer = io.StringIO()
            for label, check in [
                ("isinstance(Protocol)", lambda: isinstance(buffer, Flushable)),
                ("isinstance(ABC)", lambda: isinstance(buffer, Iterable)),
                ("hasattr", lambda: hasattr(buffer, "flush")),
            ]:
                seconds = min(timeit.repeat(check, number=20_000, repeat=3))
                print(f"{label:<22} {seconds / 20_000 * 1e9:8.0f} ns per check")
            """
        ),
        md(
            """
            **Protocol or ABC?**

            | Question | Protocol | ABC |
            | --- | --- | --- |
            | How does a class qualify? | By having the right members (structural) | By inheriting or `register` (nominal) |
            | Can third-party classes qualify without changes? | Yes | Only via `register` |
            | Checked when? | By the type checker; `isinstance` only with `@runtime_checkable` (names only) | At instantiation (missing abstract methods) and by `isinstance` |
            | Provides shared code? | Only to classes that inherit explicitly | Yes: concrete and mixin methods |
            | Typical use | Describing what a function **needs** from its arguments | A base class **family** with shared behaviour (template method) |
            | TypeScript analogue | `interface` | `abstract class` |

            Rule of thumb: describe **parameters** with Protocols, build **class hierarchies**
            with ABCs. The standard library has both: `typing.SupportsIndex` and friends are
            runtime-checkable Protocols, while `collections.abc.Sized` is an ABC with a
            structural `__subclasshook__`.
            """
        ),
        code(
            """
            print(f"{isinstance(3, typing.SupportsIndex)=}, {isinstance(3.5, typing.SupportsIndex)=}")
            print(f"{typing.is_protocol(typing.SupportsIndex)=}, {typing.is_protocol(Sized)=}")
            print(f"{isinstance([], Sized)=}, {type(Sized).__name__=}")
            """
        ),
    ]


def _duck_typing_cells() -> list[NotebookNode]:
    """2.3.4 Duck typing and polymorphism."""
    return [
        md(
            """
            ### 2.3.4 Duck typing and polymorphism

            "If it walks like a duck and quacks like a duck, it is a duck." Python code usually
            does not ask what **type** an object is, only whether it **can** do what is needed.
            That gives polymorphism without any shared base class: `len()` works on anything
            with `__len__`, including `PageRange` from 2.3.2.
            """
        ),
        code(
            '''
            def total_length(collections_of_things: Iterable[Sized]) -> int:
                """Works with any objects that have __len__."""
                return sum(len(things) for things in collections_of_things)


            mixed_collections: list[Sized] = ["chai", [1, 2, 3], {"a": 1}, PageRange(45, 10), range(5)]
            print(f"{[len(things) for things in mixed_collections]=}")
            print(f"{total_length(mixed_collections)=}")
            '''
        ),
        md(
            """
            Operators are polymorphic in the same way: `+` calls `__add__` on whatever the
            left operand is (Unit 2.4 shows how to write these methods).
            """
        ),
        code(
            """
            for left, right in [(2, 3), ("chai", " latte"), ([1], [2]), (Decimal("1.10"), Decimal("2.20"))]:
                print(f"{type(left).__name__:<8} {left!r} + {right!r} = {left + right!r}")
            """
        ),
        md(
            """
            **EAFP over type checks.** "Easier to ask forgiveness than permission": try the
            operation and handle the failure, instead of checking types first (LBYL, 1.9.6 and
            1.14.7). The type-checking version below rejects `FakeSocket` even though it would
            work perfectly; the EAFP version accepts anything with a `read()` method.
            """
        ),
        code(
            '''
            class FakeSocket:
                """Not a file at all, but it has read()."""

                def read(self) -> str:
                    return "data from the network"


            def read_all_lbyl(source: object) -> str:
                """Type checks: only the types the author thought of."""
                if isinstance(source, io.StringIO):
                    return source.read()
                if isinstance(source, str):
                    return source
                raise TypeError(f"unsupported source: {type(source).__name__}")


            def read_all(source: Any) -> str:
                """EAFP: anything with .read() works; otherwise treat it as text."""
                try:
                    reader = source.read
                except AttributeError:
                    return str(source)
                return reader()
            '''
        ),
        md(
            """
            Each source goes through both versions. `result_or_error` shows either the result or
            the `TypeError` the type-checking version raises.
            """
        ),
        code(
            '''
            def result_or_error(thunk: Callable[[], str]) -> str:
                """The call's result, or "TypeError: message" if it raised TypeError."""
                try:
                    return thunk()
                except TypeError as error:
                    return f"{type(error).__name__}: {error}"


            source_makers = [("StringIO", lambda: io.StringIO("from a buffer")), ("FakeSocket", FakeSocket)]
            source_makers.append(("str", lambda: "plain text"))
            for label, make_source in source_makers:
                lbyl_result = result_or_error(functools.partial(read_all_lbyl, make_source()))
                print(f"{label:<10} LBYL: {lbyl_result:<43} EAFP: {read_all(make_source())}")
            '''
        ),
        md(
            """
            > **Warning:** keep the `try` block **narrow**. If the `try` also covers the call
            > to `read()`, an `AttributeError` raised by a bug *inside* `read()` is swallowed and
            > silently treated as "not readable". The version above only looks up the attribute
            > inside the `try`, so the bug surfaces.
            """
        ),
        code(
            '''
            class BrokenReader:
                """read() has a bug that raises AttributeError internally."""

                def read(self) -> str:
                    return self.buffer.decode()  # bug: there is no self.buffer

                def __str__(self) -> str:
                    return "BrokenReader (fallback used: the bug is hidden)"


            def read_all_too_wide(source: Any) -> str:
                """BUG: the try block also covers the call."""
                try:
                    return source.read()
                except AttributeError:
                    return str(source)


            print(read_all_too_wide(BrokenReader()))
            print(raised_message(lambda: read_all(BrokenReader())))
            '''
        ),
        md(
            """
            **When type checks are right.** Duck typing is the default, but `isinstance` has
            its place:

            | Situation | Tool |
            | --- | --- |
            | Validating untrusted input at a boundary (JSON, CLI args) | `isinstance` against built-in types |
            | "Is this any kind of mapping / sequence?" | `isinstance(x, Mapping)` with `collections.abc`, never `type(x) is dict` |
            | Different behaviour per type, kept open for extension | `functools.singledispatch` (1.12.7) |
            | Describing what a function needs, for the type checker | a Protocol (2.3.3) |

            `singledispatch` dispatches on the type of the first argument and accepts ABCs, so
            any `Mapping` (including `EnvironmentConfig`) takes the mapping branch.
            """
        ),
        code(
            '''
            @functools.singledispatch
            def to_display(value: object) -> str:
                """Default: str()."""
                return str(value)


            @to_display.register
            def _(value: Decimal) -> str:
                return f"INR {value:,.2f}"


            @to_display.register
            def _(value: Mapping) -> str:
                return ", ".join(f"{key}={item}" for key, item in value.items())


            for value in [42, Decimal("1234.5"), {"port": 8000}, app_config]:
                print(f"{type(value).__name__:<18} -> {to_display(value)}")
            '''
        ),
        *predict_cells(
            """
            from collections.abc import Iterable

            class Countdown:
                def __getitem__(self, index):
                    if index >= 3:
                        raise IndexError
                    return 3 - index

            print(list(Countdown()))
            print(isinstance(Countdown(), Iterable))
            """,
            """
            ```text
            [3, 2, 1]
            False
            ```

            `iter()` falls back to the old sequence protocol: it calls `__getitem__(0)`,
            `__getitem__(1)`, … until `IndexError`. But `Iterable.__subclasshook__` only looks
            for `__iter__`, so the ABC check says `False`. Asking "can I iterate it?" with
            `isinstance(x, Iterable)` is therefore not fully reliable; trying `iter(x)` is.
            """,
            '''
            class Countdown:
                """Iterable only through the old __getitem__ protocol."""

                def __getitem__(self, index: int) -> int:
                    if index >= 3:
                        raise IndexError
                    return 3 - index


            print(list(Countdown()))
            print(isinstance(Countdown(), Iterable))
            ''',
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 2.3."""
    return [
        md(
            """
            ### Lab 2.3

            Four exercises. For each, complete the stub, then run the check cell. Until then
            the checks print FAIL; that is expected. Some structural checks already pass on the
            stub because the class shape is given: "Square is not a Rectangle" (exercise 1),
            "no assignment", "is a Mapping", "not a MutableMapping" and "only three methods
            written" (exercise 2), and "issubclass refused" (exercise 4). Keep them passing.

            #### Exercise 1 — a `Shape` ABC with sortable subclasses

            - `Shape(ABC)` declares an **abstract property** `area` and an **abstract method**
              `perimeter()`.
            - `Shape.__lt__(other)` compares areas, so `sorted()` orders shapes from smallest to
              largest; return `NotImplemented` when `other` is not a `Shape` (Python then raises
              `TypeError`). `sorted` needs only `<`; Unit 2.4 covers comparison methods fully.
            - `Shape.describe()` is a template method returning
              `f"{class name}: area={area:.2f}, perimeter={perimeter:.2f}"`.
            - `Circle(radius)`, `Rectangle(width, height)` and `Square(side)` are concrete
              shapes. Every dimension must be greater than zero, otherwise
              `ValueError("dimensions must be positive")`. `Square` must **not** subclass
              `Rectangle` (2.2.5).
            """
        ),
        code(
            '''
            class Shape(ABC):  # noqa: B024 (add the abstract members)
                """Abstract shape: subclasses provide area and perimeter; shapes sort by area."""

                # Declare the abstract property `area` and the abstract method `perimeter()` here.

                def __lt__(self, other: object) -> bool:
                    raise NotImplementedError("Lab 2.3: implement Shape.__lt__")

                def describe(self) -> str:
                    raise NotImplementedError("Lab 2.3: implement Shape.describe")


            class Circle(Shape):
                def __init__(self, radius: float) -> None:
                    raise NotImplementedError("Lab 2.3: implement Circle")


            class Rectangle(Shape):
                def __init__(self, width: float, height: float) -> None:
                    raise NotImplementedError("Lab 2.3: implement Rectangle")


            class Square(Shape):
                def __init__(self, side: float) -> None:
                    raise NotImplementedError("Lab 2.3: implement Square")
            '''
        ),
        md(
            """
            Run the checks. `Triangle` deliberately forgets `perimeter()`, so creating one must
            fail once `Shape` is abstract.
            """
        ),
        code(
            '''
            class Triangle(Shape):
                """Forgets perimeter()."""

                @property
                def area(self) -> float:
                    return 1.0


            run_checks(
                [
                    ("Shape is abstract", lambda: raised_error_name(Shape), "TypeError"),
                    ("incomplete subclass", lambda: raised_error_name(Triangle), "TypeError"),
                    ("abstract members", lambda: sorted(Shape.__abstractmethods__), ["area", "perimeter"]),
                    (
                        "sorted by area",
                        lambda: [
                            type(shape).__name__
                            for shape in sorted([Rectangle(3, 4), Circle(1), Square(3), Circle(2)])
                        ],
                        ["Circle", "Square", "Rectangle", "Circle"],
                    ),
                    ("less than", lambda: (Circle(1) < Square(2), Square(2) < Circle(1)), (True, False)),
                    ("describe circle", lambda: Circle(1).describe(), "Circle: area=3.14, perimeter=6.28"),
                    (
                        "describe rectangle",
                        lambda: Rectangle(3, 4).describe(),
                        "Rectangle: area=12.00, perimeter=14.00",
                    ),
                    ("describe square", lambda: Square(2.5).describe(), "Square: area=6.25, perimeter=10.00"),
                    ("area is a property", lambda: Square(3).area, 9),
                    ("Square is not a Rectangle", lambda: issubclass(Square, Rectangle), False),
                    (
                        "positive dimensions",
                        lambda: raised_message(lambda: Rectangle(0, 2)),
                        "ValueError: dimensions must be positive",
                    ),
                    ("compare with non-shape", lambda: raised_error_name(lambda: Circle(1) < 5), "TypeError"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `ReadOnlyView(Mapping)` with three methods

            `ReadOnlyView(data)` wraps another mapping **without copying it**: changes to the
            wrapped dict show through the view, but the view itself cannot be changed (item
            assignment raises `TypeError`, because `Mapping` has no `__setitem__`).

            Implement only `__getitem__`, `__iter__` and `__len__`; `get`, `keys`, `items`,
            `values`, `in` and `==` must come from `Mapping`.
            """
        ),
        code(
            '''
            class ReadOnlyView[K, V](Mapping[K, V]):
                """A live, read-only view of another mapping."""

                def __init__(self, data: Mapping[K, V]) -> None:
                    self._data = data

                def __getitem__(self, key: K) -> V:
                    raise NotImplementedError("Lab 2.3: implement ReadOnlyView.__getitem__")

                def __iter__(self) -> Iterator[K]:
                    raise NotImplementedError("Lab 2.3: implement ReadOnlyView.__iter__")

                def __len__(self) -> int:
                    raise NotImplementedError("Lab 2.3: implement ReadOnlyView.__len__")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            prices = {"soap": 49, "tea": 120}
            MAPPING_METHOD_NAMES = {
                "__getitem__",
                "__iter__",
                "__len__",
                "get",
                "keys",
                "items",
                "values",
                "__contains__",
            }


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
                    ("items (free)", lambda: list(ReadOnlyView(prices).items()), [("soap", 49), ("tea", 120)]),
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
                    ("not a MutableMapping", lambda: isinstance(ReadOnlyView(prices), MutableMapping), False),
                    (
                        "only three methods written",
                        lambda: sorted(name for name in vars(ReadOnlyView) if name in MAPPING_METHOD_NAMES),
                        ["__getitem__", "__iter__", "__len__"],
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — a `SupportsClose` Protocol

            - Make `SupportsClose` a **runtime-checkable** Protocol with one member,
              `close(self) -> None`.
            - Write `close_all(resources)`: for every item that satisfies `SupportsClose` (in
              order), call `close()`; skip items that do not. Keep going when a `close()` raises
              an `Exception`. Return `(closed_count, failures)` where `closed_count` counts the
              successful closes and `failures` is a list of
              `f"{type(resource).__name__}: {error}"` strings.
            - `resources` can be any iterable, including a generator.
            """
        ),
        code(
            '''
            class SupportsClose(Protocol):
                """Anything with a close() method. Add the member and make it runtime-checkable."""


            def close_all(resources: Iterable[object]) -> tuple[int, list[str]]:
                """Close every resource that supports close(), even if some fail."""
                raise NotImplementedError("Lab 2.3: implement close_all")
            '''
        ),
        md("Run the checks. `Recorder` and `FlakyResource` inherit from nothing."),
        code(
            '''
            class Recorder:
                """Closes cleanly and remembers it."""

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
            '''
        ),
        md(
            """
            #### Exercise 4 — a payment gateway behind a `PaymentProvider` Protocol

            Write a runtime-checkable Protocol `PaymentProvider` with three members: the
            attribute `name: str`, `charge(amount_paise, token) -> str` (returns a transaction
            id, or raises `PaymentDeclinedError`) and `refund(transaction_id) -> None`.

            Two fake providers implement it **without inheriting from it**. Both keep
            `charges: dict[str, int]` (transaction id → amount) and `refunded: list[str]`, number
            their transactions `f"{name}_{n:04d}"` from 1, and raise
            `ValueError("amount must be positive")` (a programming error, not a decline) when
            `amount_paise <= 0`. `refund` moves a charge from `charges` to `refunded` and raises
            `KeyError(transaction_id)` for an unknown id.

            | Provider | `name` | Declines with `PaymentDeclinedError(…)` |
            | --- | --- | --- |
            | `CardGateway()` | `"card"` | `"invalid card token"` unless the token starts with `"tok_"` |
            | `UpiGateway()` | `"upi"` | `"invalid UPI ID"` unless the token contains `"@"`; `"amount exceeds UPI limit"` above `UPI_LIMIT_PAISE` |

            `CheckoutService(provider)` depends only on the Protocol:

            - `pay(order_id, amount_paise, token)` returns a `PaymentResult`: status `"paid"`
              with the transaction id and message `""`, or `"declined"` with
              `transaction_id=None` and the decline message. Every result is appended to
              `self.history`. A `ValueError` from the provider is **not** caught.
            - `refund(result)` refunds a paid result through the provider; anything else raises
              `ValueError("only paid orders can be refunded")`.

            The given types:
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Your Protocol, providers and service:"),
        code(
            '''
            class PaymentProvider(Protocol):
                """What CheckoutService needs from a payment provider. Add the three members."""


            class CardGateway:
                def __init__(self) -> None:
                    raise NotImplementedError("Lab 2.3: implement CardGateway")


            class UpiGateway:
                def __init__(self) -> None:
                    raise NotImplementedError("Lab 2.3: implement UpiGateway")


            class CheckoutService:
                def __init__(self, provider: PaymentProvider) -> None:
                    raise NotImplementedError("Lab 2.3: implement CheckoutService")

                def pay(self, order_id: str, amount_paise: int, token: str) -> PaymentResult:
                    raise NotImplementedError("Lab 2.3: implement CheckoutService.pay")

                def refund(self, result: PaymentResult) -> None:
                    raise NotImplementedError("Lab 2.3: implement CheckoutService.refund")
            '''
        ),
        md(
            """
            Run the checks. `WalletGateway` is a third provider written later, inheriting from
            nothing; the service must accept it unchanged.
            """
        ),
        code(
            '''
            class WalletGateway:
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
            '''
        ),
        md("The checks themselves:"),
        code(
            """
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
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.3."""
    return [
        md(
            """
            ### Recap — Unit 2.3

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | `ABC` + `@abstractmethod` | Instantiating a class with unimplemented abstract methods raises `TypeError` | TS `abstract class` |
            | `ABCMeta` / `__abstractmethods__` | The metaclass records what is still abstract | — |
            | Abstract property | `@property` over `@abstractmethod`; a class attribute can satisfy it | TS `abstract get x()` |
            | Template method | The base owns the algorithm, subclasses fill in the steps (and optional hooks) | same pattern |
            | `collections.abc` | Write the abstract methods, inherit the mixin methods | — |
            | `register` | Virtual subclass: `isinstance` is true, no mixins, no checks | — |
            | `__subclasshook__` | Membership decided by inspecting the class (how `Iterable` works) | `Symbol.hasInstance` |
            | `Protocol` | Structural typing, checked by type checkers | TS `interface` |
            | `@runtime_checkable` | `isinstance` checks member **names** only; no `issubclass` with attributes; slow | — (interfaces are erased) |
            | Protocol vs ABC | Protocols for what a function needs; ABCs for families sharing code | `interface` vs `abstract class` |
            | Duck typing | Ask "can it?", not "is it?"; polymorphism without a base class | same |
            | EAFP | `try` the narrow operation, catch the specific error | `try/catch` |
            | `singledispatch` | Type-based dispatch that understands ABCs | — |

            **Further reading**

            - [`abc` — Abstract base classes](https://docs.python.org/3/library/abc.html),
              [`collections.abc`](https://docs.python.org/3/library/collections.abc.html)
              (the full table of ABCs and mixin methods)
            - [`typing.Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol),
              [`runtime_checkable`](https://docs.python.org/3/library/typing.html#typing.runtime_checkable),
              [`get_protocol_members`](https://docs.python.org/3/library/typing.html#typing.get_protocol_members),
              [typing spec: protocols](https://typing.python.org/en/latest/spec/protocol.html)
            - [Glossary: duck typing](https://docs.python.org/3/glossary.html#term-duck-typing),
              [EAFP](https://docs.python.org/3/glossary.html#term-EAFP),
              [`functools.singledispatch`](https://docs.python.org/3/library/functools.html#functools.singledispatch)
            - [PEP 3119 — Introducing abstract base classes](https://peps.python.org/pep-3119/),
              [PEP 544 — Protocols: structural subtyping](https://peps.python.org/pep-0544/),
              [PEP 695 — Type parameter syntax](https://peps.python.org/pep-0695/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.3 and Lab 2.3."""
    return [
        *_overview_cells(),
        *_abc_cells(),
        *_collections_abc_cells(),
        *_protocol_cells(),
        *_duck_typing_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
