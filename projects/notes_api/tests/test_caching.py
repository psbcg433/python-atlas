"""HTTP caching (ETag, 304, Cache-Control) and the Redis cache-aside for single notes."""

import fakeredis
from fastapi.testclient import TestClient

from helpers import auth_headers, create
from notes_api.cache import NoteCache, note_key


def test_etag_and_304(client: TestClient) -> None:
    """A matching If-None-Match gets an empty 304; an update changes the ETag."""
    note = create(client)
    first = client.get(f"/api/v1/notes/{note['id']}")
    etag = first.headers["etag"]
    assert (etag, first.headers["cache-control"]) == ('"1-1"', "private, no-cache")
    not_modified = client.get(f"/api/v1/notes/{note['id']}", headers={"If-None-Match": etag})
    assert (not_modified.status_code, not_modified.content, not_modified.headers["etag"]) == (
        304,
        b"",
        etag,
    )
    client.patch(f"/api/v1/notes/{note['id']}", json={"pinned": True})
    changed = client.get(f"/api/v1/notes/{note['id']}", headers={"If-None-Match": etag})
    assert (changed.status_code, changed.headers["etag"]) == (200, '"1-2"')


def test_cache_hits_misses_and_invalidation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """The first read misses, later reads hit; an update invalidates the cached copy."""
    note = create(client, title="Old")
    for _ in range(4):
        client.get(f"/api/v1/notes/{note['id']}")
    client.patch(f"/api/v1/notes/{note['id']}", json={"title": "New"})
    assert client.get(f"/api/v1/notes/{note['id']}").json()["title"] == "New"
    assert client.get("/api/v1/admin/cache-stats", headers=admin_headers).json() == {
        "hits": 3,
        "misses": 2,
        "hit_rate": 0.6,
    }


def test_cached_notes_are_still_authorized(client: TestClient) -> None:
    """A cached note is not served to another user (authorization happens after the cache)."""
    note = create(client, title="Private")
    client.get(f"/api/v1/notes/{note['id']}")  # now cached
    intruder = auth_headers(client, "intruder@example.com")
    assert client.get(f"/api/v1/notes/{note['id']}", headers=intruder).status_code == 404


def test_lists_are_not_stored(client: TestClient) -> None:
    """Lists change with every write: no-store."""
    assert client.get("/api/v1/notes").headers["cache-control"] == "private, no-store"


def test_stampede_lock_loads_once(client: TestClient, fake_redis: fakeredis.FakeAsyncRedis) -> None:
    """Ten concurrent misses on one key run the loader once; the rest wait for its result."""
    import asyncio

    cache = NoteCache(fake_redis, ttl_seconds=60)
    loads = []

    async def slow_loader() -> dict[str, object]:
        """Count calls; take a while."""
        loads.append(1)
        await asyncio.sleep(0.05)
        return {"owner_id": 1, "note": {"id": 99, "version": 1}}

    async def ten_readers() -> list[object]:
        """Concurrent cache misses."""
        return await asyncio.gather(*(cache.get_or_load(99, slow_loader) for _ in range(10)))

    results = client.portal.call(ten_readers)
    assert len(loads) == 1 and all(result == results[0] for result in results)
    ttl = client.portal.call(fake_redis.ttl, note_key(99))
    assert 54 <= ttl <= 66  # 60 s ± 10 % jitter
