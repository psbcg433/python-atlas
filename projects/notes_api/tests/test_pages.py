"""Server-rendered pages: templates, a form with redirect, HTMX fragments, static files."""

from fastapi.testclient import TestClient

from helpers import create


def test_page_lists_notes_as_html(client: TestClient) -> None:
    """GET / renders the full page with every note, escaped."""
    create(client, title="Buy <tea>", tags=["shop"])
    page = client.get("/")
    assert page.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in page.text
    assert "Buy &lt;tea&gt;" in page.text and "Buy <tea>" not in page.text


def test_htmx_search_returns_only_the_fragment(client: TestClient) -> None:
    """With HX-Request: true the response is the list fragment, not a whole page."""
    create(client, title="Tea")
    create(client, title="Rice")
    fragment = client.get("/", params={"q": "tea"}, headers={"HX-Request": "true"}).text
    assert "<html" not in fragment
    assert "Tea" in fragment and "Rice" not in fragment


def test_form_post_redirects_with_303(client: TestClient) -> None:
    """A valid form creates the note and redirects back (Post/Redirect/Get)."""
    response = client.post(
        "/notes", data={"title": "From the form", "tags": "home, todo"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://testserver/"
    note = client.get("/api/v1/notes/1").json()
    assert (note["title"], note["tags"]) == ("From the form", ["home", "todo"])


def test_invalid_form_is_shown_again_with_errors(client: TestClient) -> None:
    """An invalid form re-renders the page (422) with the message and the typed values."""
    response = client.post("/notes", data={"title": "", "body": "keep me"})
    assert response.status_code == 422
    assert "title:" in response.text and "keep me" in response.text


def test_htmx_pin_returns_one_note(client: TestClient) -> None:
    """The pin button swaps in the updated fragment of one note."""
    create(client, title="Tea")
    fragment = client.post("/notes/1/pin").text
    assert 'class="note pinned"' in fragment and "Unpin" in fragment


def test_static_css_is_served(client: TestClient) -> None:
    """StaticFiles serves the stylesheet."""
    response = client.get("/static/style.css")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
