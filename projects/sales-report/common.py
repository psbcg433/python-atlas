"""Shared inputs for the sales-report scripts: the catalog, the data generator, the store API.

Both ``slow_report.py`` and ``fast_report.py`` read their rows from ``generate_chunks()``, so
for a given ``(row_count, seed)`` they see exactly the same sales. The generator stands in for
the export from a sales database: it is not what the project optimizes, it is the input.

``fetch_store_profile()`` stands in for a remote "store directory" HTTP API. It blocks for
``SALES_NETWORK_DELAY`` seconds (default 0.05) per call, like a real round trip, and needs no
network. Tests set the variable to ``0``.
"""

import os
import random
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

YEAR = 2025
DEFAULT_ROW_COUNT = 1_000_000
DEFAULT_SEED = 42
CHUNK_ROWS = 100_000  # rows per generated chunk: the fast version never holds more than this
MAX_QUANTITY = 5

REGIONS = ("Central", "East", "North", "South", "West")
CITIES = (
    ("Delhi", "North"), ("Jaipur", "North"), ("Lucknow", "North"), ("Chandigarh", "North"),
    ("Chennai", "South"), ("Bengaluru", "South"), ("Kochi", "South"), ("Hyderabad", "South"),
    ("Kolkata", "East"), ("Bhubaneswar", "East"), ("Patna", "East"), ("Guwahati", "East"),
    ("Mumbai", "West"), ("Pune", "West"), ("Ahmedabad", "West"), ("Surat", "West"),
    ("Bhopal", "Central"), ("Indore", "Central"), ("Nagpur", "Central"), ("Raipur", "Central"),
)  # fmt: skip
STORE_CODES = tuple(f"ST-{number:02d}" for number in range(1, 41))
PRODUCT_NAMES = (
    "Basmati rice 5 kg", "Toor dal 1 kg", "Sunflower oil 1 l", "Masala chai 250 g",
    "Filter coffee 500 g", "Atta 10 kg", "Ghee 1 l", "Jaggery 1 kg", "Cashews 500 g",
    "Almonds 500 g", "Steel tiffin box", "Pressure cooker 5 l", "Non-stick tawa",
    "Mixer grinder", "Electric kettle", "Induction cooktop", "Table fan", "LED bulb 4-pack",
    "Ceiling fan", "Water purifier", "Cotton kurta", "Silk saree", "Running shoes",
    "School backpack", "Umbrella", "Raincoat", "Bedsheet set", "Bath towel pair",
    "Yoga mat", "Cricket bat", "Football", "Badminton set", "Notebook 6-pack",
    "Fountain pen", "Board game", "Jigsaw puzzle", "Bluetooth speaker", "Earphones",
    "Power bank", "Phone case", "USB charger", "Smart watch", "Desk lamp", "Office chair",
    "Bookshelf", "Wall clock", "Photo frame", "Scented candles", "Incense sticks",
    "Brass diya", "Hand soap 3-pack", "Shampoo 650 ml", "Toothpaste 4-pack",
    "Face wash", "Sunscreen", "Hair oil", "Detergent 4 kg", "Dish soap", "Floor cleaner",
    "Mosquito repellent",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Product:
    """One catalog entry. Prices are integer paise (1 rupee = 100 paise) to keep money exact."""

    sku: str
    name: str
    price_paise: int


def _build_catalog() -> tuple[Product, ...]:
    """Fixed product list with seeded prices between ₹9.00 and ₹999.00."""
    price_rng = random.Random(7)
    return tuple(
        Product(f"SKU-{index:03d}", name, price_rng.randrange(900, 99_901, 25))
        for index, name in enumerate(PRODUCT_NAMES, start=1)
    )


PRODUCTS = _build_catalog()
PRICE_PAISE = np.array([product.price_paise for product in PRODUCTS], dtype=np.int64)
DAYS_IN_YEAR = (date(YEAR + 1, 1, 1) - date(YEAR, 1, 1)).days
MONTH_OF_DAY = np.array(
    [(date(YEAR, 1, 1) + timedelta(days=day)).month - 1 for day in range(DAYS_IN_YEAR)],
    dtype=np.int64,
)  # day-of-year -> month index 0..11


@dataclass(frozen=True, slots=True)
class SalesChunk:
    """Up to CHUNK_ROWS generated sales as parallel NumPy columns (one row = one order line)."""

    first_order_number: int
    store_index: np.ndarray  # index into STORE_CODES
    product_index: np.ndarray  # index into PRODUCTS
    quantity: np.ndarray  # 1..MAX_QUANTITY
    day: np.ndarray  # day of the year, 0..DAYS_IN_YEAR-1

    def __len__(self) -> int:
        return len(self.quantity)


def generate_chunks(
    row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED
) -> Iterator[SalesChunk]:
    """Yield row_count seeded sales rows in chunks; the same arguments give the same rows."""
    if row_count < 0:
        raise ValueError(f"row_count must be >= 0, got {row_count}")
    rng = np.random.default_rng(seed)
    first = 0
    while first < row_count:
        size = min(CHUNK_ROWS, row_count - first)
        yield SalesChunk(
            first_order_number=first + 1,
            store_index=rng.integers(0, len(STORE_CODES), size),
            product_index=rng.integers(0, len(PRODUCTS), size),
            quantity=rng.integers(1, MAX_QUANTITY + 1, size),
            day=rng.integers(0, DAYS_IN_YEAR, size),
        )
        first += size


def network_delay_seconds() -> float:
    """Simulated round-trip time of the store API (SALES_NETWORK_DELAY, default 0.05 s)."""
    return float(os.environ.get("SALES_NETWORK_DELAY", "0.05"))


def fetch_store_profile(store_code: str) -> dict[str, str]:
    """Simulated GET /stores/<code>: blocks for one round trip, then returns the profile."""
    time.sleep(network_delay_seconds())  # stands in for socket I/O: releases the GIL
    city, region = CITIES[(STORE_CODES.index(store_code) * 7) % len(CITIES)]
    return {"code": store_code, "city": city, "region": region}
