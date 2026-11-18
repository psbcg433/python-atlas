"""Server-rendered pages: cookie login, CSRF, owner-only lists, HTMX fragments, static files."""

from fastapi.testclient import TestClient

from helpers import ANONYMOUS, PASSWORD, USER_EMAIL, auth_headers, register


def page_login(client: TestClient, email: str = USER_EMAIL) -> str:
    """Log in through the HTML form; return the CSRF token the pages use."""
    register(client, email)
    client.get("/login")
    csrf = client.cookies["notes_csrf"]
    form = {"email": email, "password": PASSWORD, "csrf_token": csrf}
    response = client.post("/login", data=form, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/"), response.text
    return csrf


def test_pages_redirect_to_login(anonymous: TestClient) -> None:
    """Without a session cookie the page sends the browser to the login form."""
    response = anonymous.get("/", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_login_sets_an_httponly_samesite_cookie(anonymous: TestClient) -> None:
    """The session cookie is invisible to JavaScript and not sent on cross-site POSTs."""
    register(anonymous, USER_EMAIL)
    anonymous.get("/login")
    form = {
        "email": USER_EMAIL,
        "password": PASSWORD,
        "csrf_token": anonymous.cookies["notes_csrf"],
    }
    cookie = anonymous.post("/login", data=form, follow_redirects=False).headers["set-cookie"]
    assert cookie.startswith("notes_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_wrong_password_shows_the_form_again(anonymous: TestClient) -> None:
    """A failed login re-renders the form with a 401 and keeps the email."""
    register(anonymous, USER_EMAIL)
    anonymous.get("/login")
    form = {"email": USER_EMAIL, "password": "nope", "csrf_token": anonymous.cookies["notes_csrf"]}
    response = anonymous.post("/login", data=form)
    assert response.status_code == 401 and "incorrect email or password" in response.text


def test_page_lists_only_my_notes_escaped(anonymous: TestClient) -> None:
    """The page shows the user's notes (escaped), never another user's."""
    mine = auth_headers(anonymous, USER_EMAIL)
    theirs = auth_headers(anonymous, "other@example.com")
    anonymous.post("/api/v1/notes", json={"title": "Buy <tea>"}, headers=mine)
    anonymous.post("/api/v1/notes", json={"title": "Secret plan"}, headers=theirs)
    page_login(anonymous)
    page = anonymous.get("/").text
    assert "Buy &lt;tea&gt;" in page and "Buy <tea>" not in page and "Secret plan" not in page


def test_form_post_needs_the_csrf_token(anonymous: TestClient) -> None:
    """A form post without (or with a wrong) CSRF token is refused with 403."""
    page_login(anonymous)
    assert anonymous.post("/notes", data={"title": "x"}).status_code == 403
    assert anonymous.post("/notes", data={"title": "x", "csrf_token": "forged"}).status_code == 403


def test_form_post_redirects_with_303(anonymous: TestClient) -> None:
    """A valid form creates the note and redirects back (Post/Redirect/Get)."""
    csrf = page_login(anonymous)
    form = {"title": "From the form", "tags": "home, todo", "csrf_token": csrf}
    response = anonymous.post("/notes", data=form, follow_redirects=False)
    assert response.status_code == 303
    assert "From the form" in anonymous.get("/").text


def test_invalid_form_is_shown_again_with_errors(anonymous: TestClient) -> None:
    """An invalid form re-renders the page (422) with the message and the typed values."""
    csrf = page_login(anonymous)
    response = anonymous.post("/notes", data={"title": "", "body": "keep me", "csrf_token": csrf})
    assert response.status_code == 422
    assert "title:" in response.text and "keep me" in response.text


def test_htmx_search_and_pin(anonymous: TestClient) -> None:
    """HX-Request returns the list fragment; the pin button needs the CSRF header."""
    csrf = page_login(anonymous)
    for title in ("Tea", "Rice"):
        anonymous.post("/notes", data={"title": title, "csrf_token": csrf})
    fragment = anonymous.get("/", params={"q": "tea"}, headers={"HX-Request": "true"}).text
    assert "<html" not in fragment and "Tea" in fragment and "Rice" not in fragment
    assert anonymous.post("/notes/1/pin").status_code == 403
    pinned = anonymous.post("/notes/1/pin", headers={"X-CSRF-Token": csrf}).text
    assert 'class="note pinned"' in pinned and "Unpin" in pinned


def test_logout_ends_the_session(anonymous: TestClient) -> None:
    """After logout the old cookie value no longer works (its token is denied)."""
    csrf = page_login(anonymous)
    session = anonymous.cookies["notes_session"]
    anonymous.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    anonymous.cookies.set("notes_session", session)  # an attacker replaying the stolen cookie
    response = anonymous.get("/", follow_redirects=False)
    assert response.status_code == 303


def test_static_css_is_served(anonymous: TestClient) -> None:
    """StaticFiles serves the stylesheet."""
    response = anonymous.get("/static/style.css", headers=ANONYMOUS)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
