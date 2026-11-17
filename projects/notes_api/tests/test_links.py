"""Link previews use the lifespan's shared HTTP client; respx fakes the remote sites."""

import httpx
import respx
from fastapi.testclient import TestClient

from helpers import create


@respx.mock
def test_link_titles_are_fetched(client: TestClient) -> None:
    """Each distinct link is fetched once; titles are extracted; failures are reported."""
    respx.get("https://docs.example/fastapi").respond(200, html="<title> FastAPI\n docs </title>")
    respx.get("https://slow.example/").mock(side_effect=httpx.ConnectTimeout("too slow"))
    body = (
        "read https://docs.example/fastapi and https://slow.example/ (https://docs.example/fastapi)"
    )
    create(client, body=body)
    previews = client.get("/api/v1/notes/1/links").json()
    assert previews == [
        {
            "url": "https://docs.example/fastapi",
            "status_code": 200,
            "title": "FastAPI docs",
            "error": None,
        },
        {
            "url": "https://slow.example/",
            "status_code": None,
            "title": None,
            "error": "ConnectTimeout",
        },
    ]
    assert respx.calls.call_count == 2


def test_the_client_lives_as_long_as_the_app(app: object) -> None:
    """The lifespan opens one client at startup and closes it at shutdown."""
    with TestClient(app) as client:  # type: ignore[arg-type]
        http_client = client.app.state.http_client  # type: ignore[attr-defined]
        assert not http_client.is_closed
    assert http_client.is_closed
