import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .db import Database, now
from .ratelimit import FAILURES_PER_DEVICE, FailureLimiter

SESSION_COOKIE = "spotmp3_session"
SESSION_DAYS = 30
SESSION_SECONDS = SESSION_DAYS * 24 * 3600
DEVICE_COOKIE = "spotmp3_device"
DEVICE_SECONDS = 365 * 24 * 3600
TOKEN_BYTES = 32
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
MAX_EMAIL_LENGTH = 254
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT_COST = 2 ** 14
SCRYPT_BLOCK = 8
SCRYPT_PARALLEL = 1
SCRYPT_LENGTH = 32
STARFIRE_TIMEOUT_SECONDS = 5
STARFIRE_CACHE_SECONDS = 30
SETUP_CODE_BYTES = 9
SETUP_PATH = "/setup"

log = logging.getLogger("spotmp3.auth")


class AuthError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class User:
    owner_key: str
    email: str
    is_admin: bool
    user_id: int | None = None

    def to_json(self) -> dict:
        return {"email": self.email, "isAdmin": self.is_admin}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_COST, r=SCRYPT_BLOCK, p=SCRYPT_PARALLEL, dklen=SCRYPT_LENGTH)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def password_matches(password: str, stored: str) -> bool:
    try:
        scheme, salt_text, digest_text = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(digest_text)
    actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_text), n=SCRYPT_COST, r=SCRYPT_BLOCK, p=SCRYPT_PARALLEL, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_email(value) -> str:
    email = (value or "").strip().lower() if isinstance(value, str) else ""
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
        raise AuthError("enter a valid email address")
    return email


def check_new_password(password, confirm) -> str:
    if not isinstance(password, str) or not isinstance(confirm, str):
        raise AuthError("enter the password twice")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"use at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError("that password is too long")
    if password != confirm:
        raise AuthError("the two passwords do not match")
    return password


class BuiltinAuth:
    mode = "builtin"

    def __init__(self, database: Database, limiter: FailureLimiter | None = None, device_limiter: FailureLimiter | None = None):
        self.database = database
        self.limiter = limiter or FailureLimiter()
        self.device_limiter = device_limiter or FailureLimiter(per_address=FAILURES_PER_DEVICE, before_strict=None)
        self._dummy_hash = hash_password(secrets.token_hex(8))
        self._setup_code: str | None = None
        self._setup_lock = threading.Lock()

    def needs_setup(self) -> bool:
        with self.database.connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    def _user(self, row) -> User:
        return User(owner_key=f"builtin:{row['id']}", email=row["email"], is_admin=bool(row["is_admin"]), user_id=row["id"])

    def setup_code(self) -> str | None:
        with self._setup_lock:
            if self._setup_code is None and self.needs_setup():
                self._setup_code = secrets.token_urlsafe(SETUP_CODE_BYTES)
                log.warning("no account yet: open %s and enter the setup code %s", SETUP_PATH, self._setup_code)
            return self._setup_code

    def _spend_setup_code(self, used: str) -> None:
        with self._setup_lock:
            if self._setup_code == used:
                self._setup_code = None

    def _take_turn(self, limiter: FailureLimiter, key: str) -> None:
        wait = limiter.take_turn(key)
        if wait:
            raise AuthError(f"too many attempts, try again in {wait // 60 + 1} min", status=429)

    def _check_setup_code(self, code, expected: str, client_address: str) -> None:
        self._take_turn(self.limiter, client_address)
        if not isinstance(code, str) or not hmac.compare_digest(code.strip().encode(), expected.encode()):
            log.warning("wrong setup code from %s", client_address)
            raise AuthError("that setup code is wrong; SpotMP3 writes it to its log when it starts", status=401)
        self.limiter.succeeded(client_address)

    def create_first_admin(self, code, email, password, confirm, client_address: str = "unknown") -> str:
        expected = self.setup_code()
        if expected is None:
            raise AuthError("setup is already finished", status=403)
        self._check_setup_code(code, expected, client_address)
        address = clean_email(email)
        secret = check_new_password(password, confirm)
        with self.database.connect() as connection:
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                raise AuthError("setup is already finished", status=403)
            cursor = connection.execute("INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
                                        (address, hash_password(secret), now()))
            token = self._start_session(connection, cursor.lastrowid)
        self._spend_setup_code(expected)
        return token

    def _start_session(self, connection, user_id: int) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        connection.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (_token_hash(token), user_id, now() + SESSION_SECONDS))
        return token

    def _known_device(self, email: str, device_token) -> str | None:
        if not isinstance(device_token, str) or not device_token:
            return None
        device_hash = _token_hash(device_token)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sign_in_devices JOIN users ON users.id = sign_in_devices.user_id "
                "WHERE sign_in_devices.token_hash = ? AND users.email = ? AND sign_in_devices.created_at > ?",
                (device_hash, email, now() - DEVICE_SECONDS),
            ).fetchone()
        return device_hash if row else None

    def _sign_in_bucket(self, email: str, client_address: str, device_token) -> tuple[FailureLimiter, str]:
        device_hash = self._known_device(email, device_token)
        if device_hash is not None:
            return self.device_limiter, device_hash
        return self.limiter, client_address

    def sign_in(self, email, password, client_address: str, device_token=None) -> str:
        if not isinstance(email, str) or not isinstance(password, str) or len(email) > MAX_EMAIL_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
            raise AuthError("email or password is too long", status=400)
        address = email.strip().lower()
        limiter, key = self._sign_in_bucket(address, client_address, device_token)
        self._take_turn(limiter, key)
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email = ?", (address,)).fetchone()
            accepted = password_matches(password, row["password_hash"] if row else self._dummy_hash) and row is not None
            token = None
            if accepted:
                connection.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
                token = self._start_session(connection, row["id"])
        if token is None:
            raise AuthError("wrong email or password", status=401)
        limiter.succeeded(key)
        return token

    def device_token_for_session(self, session_token: str, known_device_token=None) -> str | None:
        with self.database.connect() as connection:
            session = connection.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (_token_hash(session_token),)).fetchone()
            if session is None:
                return None
            oldest = now() - DEVICE_SECONDS
            if isinstance(known_device_token, str) and known_device_token and connection.execute(
                    "SELECT 1 FROM sign_in_devices WHERE token_hash = ? AND user_id = ? AND created_at > ?",
                    (_token_hash(known_device_token), session["user_id"], oldest)).fetchone():
                return None
            connection.execute("DELETE FROM sign_in_devices WHERE created_at <= ?", (oldest,))
            device_token = secrets.token_urlsafe(TOKEN_BYTES)
            connection.execute("INSERT INTO sign_in_devices (token_hash, user_id, created_at) VALUES (?, ?, ?)",
                               (_token_hash(device_token), session["user_id"], now()))
        return device_token

    def sign_out(self, token: str | None) -> None:
        if not token:
            return
        with self.database.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def current_user(self, token: str | None, cookie_header: str | None = None) -> User | None:
        if not token:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (_token_hash(token), now()),
            ).fetchone()
        return self._user(row) if row else None

    def list_accounts(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT id, email, is_admin, created_at FROM users ORDER BY id").fetchall()
        return [{"id": row["id"], "email": row["email"], "isAdmin": bool(row["is_admin"]), "createdAt": row["created_at"]} for row in rows]

    def add_account(self, email, password, confirm, is_admin: bool) -> dict:
        address = clean_email(email)
        secret = check_new_password(password, confirm)
        with self.database.connect() as connection:
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (address,)).fetchone():
                raise AuthError("an account with that email already exists", status=409)
            cursor = connection.execute("INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                                        (address, hash_password(secret), 1 if is_admin else 0, now()))
        return {"id": cursor.lastrowid, "email": address, "isAdmin": bool(is_admin)}

    def delete_account(self, account_id: int, acting: User) -> str:
        if account_id == acting.user_id:
            raise AuthError("you can't delete your own account")
        with self.database.connect() as connection:
            row = connection.execute("SELECT email FROM users WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise AuthError("no such account", status=404)
            connection.execute("DELETE FROM users WHERE id = ?", (account_id,))
        return f"builtin:{account_id}"


class StarfireAuth:
    mode = "starfire"

    def __init__(self, me_url: str, opener=urllib.request.urlopen):
        self.me_url = me_url
        self._open = opener
        self._cache: dict[str, tuple[float, User | None]] = {}
        self._lock = threading.Lock()

    def needs_setup(self) -> bool:
        return False

    def _ask_starfire(self, cookie_header: str) -> User | None:
        request = urllib.request.Request(self.me_url, headers={"Cookie": cookie_header, "Accept": "application/json"})
        try:
            with self._open(request, timeout=STARFIRE_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read(64 * 1024))
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                return None
            raise AuthError(f"the account service answered {error.code}", status=502) from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise AuthError("the account service could not be reached", status=502) from error
        identity = body.get("id") if isinstance(body, dict) else None
        email = body.get("email") if isinstance(body, dict) else None
        if identity is None or not isinstance(email, str):
            raise AuthError("the account service sent an unexpected answer", status=502)
        return User(owner_key=f"starfire:{identity}", email=email, is_admin=body.get("role") == "admin")

    def current_user(self, token: str | None, cookie_header: str | None = None) -> User | None:
        if not cookie_header:
            return None
        key = hashlib.sha256(cookie_header.encode()).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        user = self._ask_starfire(cookie_header)
        with self._lock:
            if len(self._cache) > 1000:
                self._cache.clear()
            self._cache[key] = (time.monotonic() + STARFIRE_CACHE_SECONDS, user)
        return user
