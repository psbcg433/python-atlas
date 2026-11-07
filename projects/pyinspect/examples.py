"""Sample workloads for trying ``python -m pyinspect memory``."""

_PRICE_CACHE: dict[str, float] = {}


def build_price_table() -> list[dict[str, object]]:
    """Return 20 000 price rows: the returned list is memory held after the call."""
    return [{"sku": f"SKU-{number:05d}", "price": number * 1.5} for number in range(20_000)]


def fill_price_cache() -> int:
    """Add 10 000 entries to a module-level cache that is never emptied (a leak)."""
    start = len(_PRICE_CACHE)
    for number in range(start, start + 10_000):
        _PRICE_CACHE[f"SKU-{number:05d}"] = number * 1.5
    return len(_PRICE_CACHE)


def churn_temporaries() -> int:
    """Allocate a lot temporarily but keep almost nothing: high peak, tiny retained size."""
    total = 0
    for _ in range(20):
        block = [str(number) * 10 for number in range(5_000)]
        total += len(block)
    return total
