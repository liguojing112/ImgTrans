from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import re
import secrets
import time


SESSION_COOKIE = "imgtrans_admin_session"
LOGIN_NONCE_COOKIE = "imgtrans_login_nonce"


class AdminSecurityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdminSession:
    username: str
    nonce: str
    expires_at: datetime


class AdminSecurity:
    def __init__(
        self,
        username: str,
        password_hash: str,
        session_secret: str,
        session_ttl_seconds: int,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username):
            raise AdminSecurityError("Administrator username is invalid")
        if len(session_secret) < 32:
            raise AdminSecurityError("Administrator session secret is too short")
        _parse_password_hash(password_hash)
        if not 900 <= session_ttl_seconds <= 86_400:
            raise AdminSecurityError("Administrator session TTL is invalid")
        self._username = username
        self._password_hash = password_hash
        self._secret = session_secret.encode("utf-8")
        self._session_ttl_seconds = session_ttl_seconds

    @property
    def username(self) -> str:
        return self._username

    @property
    def session_ttl_seconds(self) -> int:
        return self._session_ttl_seconds

    def verify_credentials(self, username: str, password: str) -> bool:
        username_ok = hmac.compare_digest(username, self._username)
        password_ok = verify_password(password, self._password_hash)
        return username_ok and password_ok

    def create_session(self) -> str:
        payload = {
            "v": 1,
            "u": self._username,
            "n": secrets.token_urlsafe(24),
            "exp": int(time.time()) + self._session_ttl_seconds,
        }
        encoded = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        return f"{encoded}.{self._sign('session', encoded)}"

    def parse_session(self, value: str | None) -> AdminSession | None:
        if value is None or len(value) > 2048 or "." not in value:
            return None
        encoded, signature = value.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign("session", encoded)):
            return None
        try:
            payload = json.loads(_b64decode(encoded))
            if set(payload) != {"v", "u", "n", "exp"}:
                return None
            if payload["v"] != 1 or payload["u"] != self._username:
                return None
            if not isinstance(payload["n"], str) or len(payload["n"]) > 128:
                return None
            expires = int(payload["exp"])
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if expires <= int(time.time()):
            return None
        return AdminSession(
            username=self._username,
            nonce=payload["n"],
            expires_at=datetime.fromtimestamp(expires, timezone.utc),
        )

    def create_login_nonce(self) -> tuple[str, str]:
        nonce = secrets.token_urlsafe(24)
        return nonce, self._sign("login", nonce)

    def verify_login_csrf(self, nonce: str | None, token: str) -> bool:
        if nonce is None or len(nonce) > 256:
            return False
        return hmac.compare_digest(token, self._sign("login", nonce))

    def csrf_token(self, session: AdminSession) -> str:
        return self._sign("csrf", session.nonce)

    def verify_csrf(self, session: AdminSession, token: str) -> bool:
        return hmac.compare_digest(token, self.csrf_token(session))

    def _sign(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._secret,
            f"{purpose}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def hash_admin_password(password: str) -> str:
    if len(password) < 12:
        raise AdminSecurityError("Administrator password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return "scrypt$16384$8$1$" + _b64encode(salt) + "$" + _b64encode(digest)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        n, r, p, salt, expected = _parse_password_hash(encoded_hash)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, TypeError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(actual, expected)


def _parse_password_hash(value: str) -> tuple[int, int, int, bytes, bytes]:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = value.split("$")
        if algorithm != "scrypt":
            raise ValueError
        n, r, p = int(n_value), int(r_value), int(p_value)
        salt = _b64decode(salt_value)
        digest = _b64decode(digest_value)
    except (ValueError, TypeError) as error:
        raise AdminSecurityError("Administrator password hash is invalid") from error
    if n != 2**14 or r != 8 or p != 1 or len(salt) != 16 or len(digest) != 32:
        raise AdminSecurityError("Administrator password hash parameters are invalid")
    return n, r, p, salt, digest


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)

