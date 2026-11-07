import pytest

from spotmp3 import auth as auth_module
from spotmp3.auth import AuthError, StarfireAuth, hash_password, password_matches

PASSWORD = "correct horse battery"


def test_password_hashes_round_trip():
    stored = hash_password(PASSWORD)
    assert password_matches(PASSWORD, stored)
    assert not password_matches("wrong password!", stored)
    assert not password_matches(PASSWORD, "garbage")


def test_first_run_setup_happens_once(auth):
    assert auth.needs_setup()
    token = auth.create_first_admin("Admin@Example.com ", PASSWORD, PASSWORD)
    user = auth.current_user(token)
    assert (user.email, user.is_admin) == ("admin@example.com", True)
    assert not auth.needs_setup()
    with pytest.raises(AuthError) as refused:
        auth.create_first_admin("other@example.com", PASSWORD, PASSWORD)
    assert refused.value.status == 403


@pytest.mark.parametrize("email, password, confirm", [
    ("not-an-email", PASSWORD, PASSWORD),
    ("a@example.com", "short", "short"),
    ("a@example.com", PASSWORD, PASSWORD + "x"),
    ("a@example.com", None, None),
])
def test_setup_validates(auth, email, password, confirm):
    with pytest.raises(AuthError):
        auth.create_first_admin(email, password, confirm)


def test_sign_in_sign_out(auth):
    auth.create_first_admin("admin@example.com", PASSWORD, PASSWORD)
    token = auth.sign_in("ADMIN@example.com", PASSWORD, "1.2.3.4")
    assert auth.current_user(token).email == "admin@example.com"
    auth.sign_out(token)
    assert auth.current_user(token) is None
    assert auth.current_user(None) is None


def test_lockout_after_five_failures(auth):
    auth.create_first_admin("admin@example.com", PASSWORD, PASSWORD)
    for _ in range(5):
        with pytest.raises(AuthError) as failed:
            auth.sign_in("admin@example.com", "wrong password!", "1.2.3.4")
        assert failed.value.status == 401
    with pytest.raises(AuthError) as locked:
        auth.sign_in("admin@example.com", PASSWORD, "1.2.3.4")
    assert locked.value.status == 429
    assert auth.sign_in("admin@example.com", PASSWORD, "5.6.7.8")


def test_unknown_email_fails_like_a_wrong_password(auth):
    auth.create_first_admin("admin@example.com", PASSWORD, PASSWORD)
    with pytest.raises(AuthError, match="wrong email or password"):
        auth.sign_in("nobody@example.com", PASSWORD, "1.2.3.4")


def test_admin_adds_and_removes_accounts(auth):
    token = auth.create_first_admin("admin@example.com", PASSWORD, PASSWORD)
    admin = auth.current_user(token)
    added = auth.add_account("friend@example.com", PASSWORD, PASSWORD, False)
    with pytest.raises(AuthError):
        auth.add_account("friend@example.com", PASSWORD, PASSWORD, False)
    friend_token = auth.sign_in("friend@example.com", PASSWORD, "1.1.1.1")
    assert auth.delete_account(added["id"], admin) == f"builtin:{added['id']}"
    assert auth.current_user(friend_token) is None
    with pytest.raises(AuthError):
        auth.delete_account(admin.user_id, admin)


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, limit):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_starfire_mode_asks_starfire_and_caches(monkeypatch):
    calls = []

    def opener(request, timeout):
        calls.append(request.get_header("Cookie"))
        return FakeResponse(b'{"id": 7, "email": "drew@example.com", "role": "admin"}')

    starfire = StarfireAuth("http://127.0.0.1:8090/api/auth/me", opener)
    user = starfire.current_user(None, "session=abc")
    assert (user.owner_key, user.email, user.is_admin) == ("starfire:7", "drew@example.com", True)
    starfire.current_user(None, "session=abc")
    assert calls == ["session=abc"]
    assert starfire.current_user(None, None) is None


def test_starfire_signed_out_and_unreachable():
    import urllib.error

    def signed_out(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)

    def unreachable(request, timeout):
        raise urllib.error.URLError("down")

    assert StarfireAuth("http://x/me", signed_out).current_user(None, "a=b") is None
    with pytest.raises(AuthError) as failed:
        StarfireAuth("http://x/me", unreachable).current_user(None, "a=b")
    assert failed.value.status == 502
    assert auth_module.STARFIRE_CACHE_SECONDS > 0
