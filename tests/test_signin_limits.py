import ipaddress
import threading
import time
from dataclasses import replace

import pytest
import waitress

from conftest import CLIENT_HEADERS, TEST_PASSWORD, set_up_admin
from spotmp3 import auth as auth_module
from spotmp3 import cli
from spotmp3.auth import AuthError, BuiltinAuth
from spotmp3.config import ConfigError, load_settings
from spotmp3.ratelimit import (FAILURES_BEFORE_STRICT, STRICT_FAILURES_PER_NETWORK, FailureLimiter, failure_bucket,
                               failure_source, visitor_address)
from spotmp3.site_settings import SiteSettings
from spotmp3.web import create_app

ADMIN = "admin@example.com"
FRIEND = "friend@example.com"
WRONG = "wrong password!"
FIFTEEN_MINUTES = 15 * 60
ATTACKER = "203.0.113.9"
OWNER_ADDRESS = "198.51.100.4"
PROXY = "192.0.2.10"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def limited(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock), device_limiter=FailureLimiter(clock=clock, before_strict=None))
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    auth.add_account(FRIEND, TEST_PASSWORD, TEST_PASSWORD, False)
    return auth


def status_of(action) -> int:
    try:
        action()
    except AuthError as error:
        return error.status
    return 200


def wrong_sign_in(auth, address, email=ADMIN, device=None) -> int:
    return status_of(lambda: auth.sign_in(email, WRONG, address, device))


def device_for(auth, email=ADMIN, address=OWNER_ADDRESS) -> str:
    return auth.device_token_for_session(auth.sign_in(email, TEST_PASSWORD, address))


@pytest.mark.parametrize("address, strict, bucket", [
    ("203.0.113.9", False, "203.0.113.9"),
    ("::ffff:203.0.113.9", False, "203.0.113.9"),
    ("2001:db8:1:2::1", False, "2001:db8:1:2::/64"),
    ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", False, "2001:db8:1:2::/64"),
    ("203.0.113.9", True, "203.0.113.0/24"),
    ("2001:db8:1:2::1", True, "2001:db8:1::/48"),
    ("unknown", False, "unknown"),
])
def test_addresses_are_counted_by_network(address, strict, bucket):
    assert failure_bucket(address, strict=strict) == bucket


@pytest.mark.parametrize("address, source", [
    ("203.0.113.9", "203.0.113.9"),
    ("::ffff:203.0.113.9", "203.0.113.9"),
    ("2001:db8:1:2::1", "2001:db8:1::/56"),
    ("2001:db8:1:ff:aaaa:bbbb:cccc:dddd", "2001:db8:1::/56"),
    ("2001:db8:1:100::1", "2001:db8:1:100::/56"),
    ("unknown", "unknown"),
])
def test_strict_mode_counts_one_ipv6_home_line_as_one_address(address, source):
    assert failure_source(address) == source


def test_wrong_passwords_sent_at_once_cannot_outrun_the_limit(limited, monkeypatch):
    checked = []
    real_check = auth_module.password_matches

    def slow_check(password, stored):
        checked.append(password)
        time.sleep(0.2)
        return real_check(password, stored)

    monkeypatch.setattr(auth_module, "password_matches", slow_check)
    start = threading.Barrier(16)
    statuses = []

    def attempt():
        start.wait()
        statuses.append(wrong_sign_in(limited, ATTACKER))

    threads = [threading.Thread(target=attempt) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(checked) == 5
    assert sorted(statuses) == [401] * 5 + [429] * 11


def test_addresses_in_one_ipv6_network_share_one_allowance(limited):
    for host in range(1, 6):
        assert wrong_sign_in(limited, f"2001:db8:1:2::{host}") == 401
    assert wrong_sign_in(limited, "2001:db8:1:2::ffff") == 429
    assert wrong_sign_in(limited, "2001:db8:1:3::1") == 401


def test_one_address_cannot_try_many_accounts_past_the_limit(limited):
    for number in range(5):
        assert wrong_sign_in(limited, ATTACKER, f"made-up-{number}@example.com") == 401
    assert wrong_sign_in(limited, ATTACKER, FRIEND) == 429


def test_many_failures_from_everywhere_leave_each_address_one_try_and_each_network_three(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock, before_strict=4))
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    for host in range(1, 5):
        assert wrong_sign_in(auth, f"192.0.2.{host * 50}") == 401
    assert wrong_sign_in(auth, "198.51.100.1") == 401
    assert wrong_sign_in(auth, "198.51.100.1") == 429
    assert wrong_sign_in(auth, "198.51.100.2") == 401
    assert wrong_sign_in(auth, "198.51.100.3") == 401
    assert wrong_sign_in(auth, "198.51.100.4") == 429
    assert wrong_sign_in(auth, "203.0.113.1") == 401
    clock.now += FIFTEEN_MINUTES + 1
    assert wrong_sign_in(auth, "198.51.100.1") == 401
    assert wrong_sign_in(auth, "198.51.100.1") == 401


def test_once_strict_a_neighbour_s_wrong_password_leaves_the_owner_a_new_browser(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock, before_strict=4))
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    for host in range(1, 5):
        assert wrong_sign_in(auth, f"203.0.113.{host}") == 401
    assert wrong_sign_in(auth, "192.0.2.1") == 401
    assert auth.sign_in(ADMIN, TEST_PASSWORD, "192.0.2.99")
    assert wrong_sign_in(auth, "2001:db8:bb:1::1") == 401
    assert auth.sign_in(ADMIN, TEST_PASSWORD, "2001:db8:bb:ffff::9")


def test_once_strict_three_networks_of_one_ipv6_home_line_leave_the_owner_a_new_browser(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock, before_strict=4))
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    for host in range(1, 5):
        assert wrong_sign_in(auth, f"203.0.113.{host}") == 401
    neighbour_line = [wrong_sign_in(auth, f"2001:db8:bb:{subnet}::1") for subnet in (1, 2, 3)]
    assert neighbour_line == [401, 429, 429]
    assert auth.sign_in(ADMIN, TEST_PASSWORD, "2001:db8:bb:ffff::9")


def test_once_strict_an_account_holder_s_own_sign_in_does_not_give_the_network_its_tries_back(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock, before_strict=4))
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    auth.add_account(FRIEND, TEST_PASSWORD, TEST_PASSWORD, False)
    for host in range(1, 5):
        assert wrong_sign_in(auth, f"203.0.113.{host}") == 401
    got = []
    for round_number in range(6):
        got += [wrong_sign_in(auth, f"192.0.2.{round_number * 10 + host}") for host in (1, 2)]
        got.append(status_of(lambda: auth.sign_in(FRIEND, TEST_PASSWORD, "192.0.2.200")))
    assert got[:6] == [401, 401, 200, 401, 429, 429]
    assert got[6:] == [429] * 12
    assert got.count(401) == STRICT_FAILURES_PER_NETWORK


def test_a_right_password_in_strict_mode_leaves_the_other_addresses_failures_counted(clock):
    limiter = FailureLimiter(clock=clock, before_strict=2)
    assert limiter.take_turn("198.51.100.1") == 0
    assert limiter.take_turn("198.51.100.2") == 0
    assert limiter.take_turn("203.0.113.1") == 0
    assert limiter.take_turn("203.0.113.2") == 0
    assert limiter.take_turn("203.0.113.200") == 0
    limiter.succeeded("203.0.113.200")
    assert limiter.take_turn("203.0.113.3") == 0
    assert limiter.take_turn("203.0.113.4") > 0
    assert limiter.seconds_blocked("203.0.113.200") > 0


def address_in_one_ipv6_56(index: int) -> str:
    return str(ipaddress.ip_address(int(ipaddress.ip_address("2001:db8:5:100::")) + ((index % 256) << 64) + 1))


@pytest.mark.parametrize("neighbour, owner", [
    ("198.51.100.200", "198.51.100.7"),
    ("2001:db8:9:1::1", "2001:db8:9:ffff::7"),
])
def test_a_neighbour_trying_whenever_allowed_for_two_hours_never_keeps_the_owner_out(clock, neighbour, owner):
    limiter = FailureLimiter(clock=clock)
    attempts = neighbour_checked = owner_checks = owner_refused = 0
    for second in range(2 * 3600):
        clock.now += 1
        for _ in range(4):
            limiter.take_turn(address_in_one_ipv6_56(attempts))
            attempts += 1
        if second < 60:
            continue
        if limiter.take_turn(neighbour) == 0:
            neighbour_checked += 1
        if second % 60 == 59:
            owner_checks += 1
            owner_refused += limiter.seconds_blocked(owner) > 0
            assert len(limiter._everyone) >= FAILURES_BEFORE_STRICT
    assert neighbour_checked == 8
    assert (owner_checks, owner_refused) == (119, 0)


def test_old_failures_are_forgotten_after_the_window(limited, clock):
    for _attempt in range(5):
        assert wrong_sign_in(limited, ATTACKER) == 401
    assert status_of(lambda: limited.sign_in(ADMIN, TEST_PASSWORD, ATTACKER)) == 429
    clock.now += FIFTEEN_MINUTES + 1
    assert limited.sign_in(ADMIN, TEST_PASSWORD, ATTACKER)


def test_a_known_browser_keeps_its_own_allowance_on_a_shared_address(limited):
    device = device_for(limited)
    for _attempt in range(5):
        assert wrong_sign_in(limited, PROXY) == 401
    assert status_of(lambda: limited.sign_in(ADMIN, TEST_PASSWORD, PROXY)) == 429
    assert limited.sign_in(ADMIN, TEST_PASSWORD, PROXY, device)


def test_a_known_browser_is_limited_too(limited):
    device = device_for(limited)
    for _attempt in range(5):
        assert wrong_sign_in(limited, OWNER_ADDRESS, device=device) == 401
    assert wrong_sign_in(limited, OWNER_ADDRESS, device=device) == 429
    assert wrong_sign_in(limited, OWNER_ADDRESS) == 401


def test_a_device_cookie_has_five_tries_of_its_own_by_default(database):
    auth = BuiltinAuth(database)
    auth.create_first_admin(auth.setup_code(), ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)
    device = device_for(auth)
    for _attempt in range(5):
        assert wrong_sign_in(auth, OWNER_ADDRESS, device=device) == 401
    assert wrong_sign_in(auth, OWNER_ADDRESS, device=device) == 429


def test_a_device_cookie_only_helps_its_own_account(limited):
    friend_device = device_for(limited, FRIEND)
    for _attempt in range(5):
        assert wrong_sign_in(limited, PROXY) == 401
    assert status_of(lambda: limited.sign_in(ADMIN, TEST_PASSWORD, PROXY, friend_device)) == 429


@pytest.mark.parametrize("device", ["", "made-up", "a" * 43, None, 7])
def test_an_unknown_device_cookie_counts_as_the_address(limited, device):
    for _attempt in range(5):
        wrong_sign_in(limited, ATTACKER, device=device)
    assert status_of(lambda: limited.sign_in(ADMIN, TEST_PASSWORD, ATTACKER, device)) == 429


def test_device_cookies_end_with_the_account(limited):
    friend_device = device_for(limited, FRIEND)
    admin = limited.current_user(limited.sign_in(ADMIN, TEST_PASSWORD, OWNER_ADDRESS))
    friend_id = next(account["id"] for account in limited.list_accounts() if account["email"] == FRIEND)
    limited.delete_account(friend_id, admin)
    limited.add_account(FRIEND, TEST_PASSWORD, TEST_PASSWORD, False)
    for _attempt in range(5):
        wrong_sign_in(limited, PROXY, FRIEND)
    assert status_of(lambda: limited.sign_in(FRIEND, TEST_PASSWORD, PROXY, friend_device)) == 429


def test_a_browser_with_a_device_cookie_is_not_given_another(limited):
    device = device_for(limited)
    assert limited.device_token_for_session(limited.sign_in(ADMIN, TEST_PASSWORD, OWNER_ADDRESS, device), device) is None
    friend_session = limited.sign_in(FRIEND, TEST_PASSWORD, OWNER_ADDRESS)
    assert limited.device_token_for_session(friend_session, device) not in (None, device)
    assert limited.device_token_for_session("not-a-session") is None


def test_wrong_setup_codes_count_against_the_visitor_address(database, clock):
    auth = BuiltinAuth(database, limiter=FailureLimiter(clock=clock))
    code = auth.setup_code()
    for host in range(1, 6):
        assert status_of(lambda: auth.create_first_admin("wrong-code", ADMIN, TEST_PASSWORD, TEST_PASSWORD, f"2001:db8:1:2::{host}")) == 401
    assert status_of(lambda: auth.create_first_admin(code, ADMIN, TEST_PASSWORD, TEST_PASSWORD, "2001:db8:1:2::9")) == 429
    assert auth.create_first_admin(code, ADMIN, TEST_PASSWORD, TEST_PASSWORD, OWNER_ADDRESS)


@pytest.mark.parametrize("peer, forwarded, client", [
    (PROXY, "203.0.113.9", "203.0.113.9"),
    (PROXY, "198.51.100.1, 203.0.113.9", "203.0.113.9"),
    (PROXY, "203.0.113.9, 10.1.1.1", "203.0.113.9"),
    (PROXY, "10.1.1.1", "10.1.1.1"),
    (PROXY, "", PROXY),
    (PROXY, None, PROXY),
    (PROXY, "not-an-address", PROXY),
    (PROXY, "203.0.113.9, not-an-address", PROXY),
    ("192.0.2.11", "203.0.113.9", "192.0.2.11"),
    ("::1", "203.0.113.9", "::1"),
])
def test_the_forwarded_address_is_believed_only_from_a_trusted_proxy(peer, forwarded, client):
    trusted = (ipaddress.ip_network(PROXY), ipaddress.ip_network("10.0.0.0/8"))
    assert visitor_address(peer, forwarded, trusted) == client


def test_without_trusted_proxies_the_forwarded_address_is_never_read():
    assert visitor_address("127.0.0.1", ATTACKER, ()) == "127.0.0.1"


def app_with(settings, auth, jobs, worker, fake_youtube, database, **changes):
    application = create_app(replace(settings, **changes), auth, jobs, worker, fake_youtube, SiteSettings(database, settings))
    application.testing = True
    return application


def web_sign_in(browser, password=TEST_PASSWORD, forwarded=None):
    headers = dict(CLIENT_HEADERS)
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    return browser.post("/api/signin", json={"email": ADMIN, "password": password}, headers=headers)


def device_cookie(response) -> str:
    return next(value for value in response.headers.getlist("Set-Cookie") if value.startswith("spotmp3_device="))


def test_behind_a_listed_proxy_each_visitor_is_counted_on_its_own(settings, auth, jobs, worker, fake_youtube, database):
    application = app_with(settings, auth, jobs, worker, fake_youtube, database, trusted_proxies=("127.0.0.1",))
    set_up_admin(application.test_client())
    attacker = application.test_client()
    for _attempt in range(5):
        assert web_sign_in(attacker, WRONG, ATTACKER).status_code == 401
    assert web_sign_in(attacker, WRONG, ATTACKER).status_code == 429
    assert web_sign_in(application.test_client(), forwarded="198.51.100.7").status_code == 200


def test_the_forwarded_address_from_an_unlisted_peer_is_ignored(settings, auth, jobs, worker, fake_youtube, database):
    application = app_with(settings, auth, jobs, worker, fake_youtube, database)
    set_up_admin(application.test_client())
    attacker = application.test_client()
    for host in range(1, 6):
        assert web_sign_in(attacker, WRONG, f"203.0.113.{host}").status_code == 401
    assert web_sign_in(application.test_client(), forwarded="198.51.100.7").status_code == 429


def test_a_browser_that_signed_in_before_is_not_locked_out_by_others(settings, auth, jobs, worker, fake_youtube, database):
    application = app_with(settings, auth, jobs, worker, fake_youtube, database)
    owner = application.test_client()
    made = set_up_admin(owner)
    assert "HttpOnly" in device_cookie(made) and "Path=/api/signin" in device_cookie(made)
    attacker = application.test_client()
    for _attempt in range(5):
        assert web_sign_in(attacker, WRONG).status_code == 401
    assert web_sign_in(attacker).status_code == 429
    again = web_sign_in(owner)
    assert again.status_code == 200
    assert not any(value.startswith("spotmp3_device=") for value in again.headers.getlist("Set-Cookie"))


def settings_from(monkeypatch, tmp_path, **values):
    monkeypatch.chdir(tmp_path)
    for name in ("AUTH_MODE", "TRUSTED_PROXIES", "SECURE_COOKIES", "ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return load_settings()


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0", "10.0.0.5/8", "not-an-address"])
def test_wide_or_odd_trusted_proxies_are_refused(monkeypatch, tmp_path, value):
    with pytest.raises(ConfigError, match="TRUSTED_PROXIES"):
        settings_from(monkeypatch, tmp_path, TRUSTED_PROXIES=value)


def test_trusted_proxies_are_read_with_built_in_accounts_only(monkeypatch, tmp_path):
    assert settings_from(monkeypatch, tmp_path, TRUSTED_PROXIES="127.0.0.1, 10.0.0.0/8").trusted_proxies == ("127.0.0.1", "10.0.0.0/8")
    assert settings_from(monkeypatch, tmp_path, AUTH_MODE="starfire", TRUSTED_PROXIES="0.0.0.0/0").trusted_proxies == ()


@pytest.mark.parametrize("values, options", [
    ({"TRUSTED_PROXIES": "127.0.0.1"}, {"clear_untrusted_proxy_headers": False}),
    ({}, {}),
    ({"AUTH_MODE": "starfire", "TRUSTED_PROXIES": "127.0.0.1"}, {}),
])
def test_waitress_keeps_x_forwarded_for_only_for_built_in_accounts_behind_a_listed_proxy(monkeypatch, tmp_path, values, options):
    assert cli.waitress_options(settings_from(monkeypatch, tmp_path, **values)) == options


def test_serve_hands_the_waitress_options_to_waitress(monkeypatch, tmp_path):
    settings_from(monkeypatch, tmp_path, TRUSTED_PROXIES="127.0.0.1", YTDLP_AUTO_UPDATE="false")
    given = {}
    monkeypatch.setattr(waitress, "serve", lambda app, **options: given.update(options))
    monkeypatch.setattr(cli, "check_programs", lambda: None)
    monkeypatch.setattr(cli.Worker, "start", lambda worker: None)
    monkeypatch.setattr(cli.Worker, "stop", lambda worker: None)
    cli.serve()
    assert given["clear_untrusted_proxy_headers"] is False
