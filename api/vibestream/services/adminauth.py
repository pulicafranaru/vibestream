"""Administrator password (scrypt), sessions, sign-in throttling and the first-claim setup code."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from ..db import session_scope
from ..models import AdminAccount, AdminSession, utcnow

log = logging.getLogger(__name__)

COOKIE = "vs_admin"
IDLE = timedelta(hours=12)
LIFETIME = timedelta(days=7)
MIN_PASSWORD = 10

# scrypt: 2^15 rounds of 8 x 128 bytes, 32 MB of memory per guess.
_N, _R, _P = 2 ** 15, 8, 1

PER_ADDRESS_FREE = 5
FIRST_WAIT = 30
LONGEST_WAIT = 15 * 60
GLOBAL_MISSES = 30
GLOBAL_WINDOW = 60 * 60

# Without confusables (0/O, 1/I/L), so it can be read off a log and typed.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class AuthError(Exception):
    def __init__(self, status: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r),
                             p=int(p), maxmem=64 * 1024 * 1024, dklen=len(digest) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


def check_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(422, f"Use at least {MIN_PASSWORD} characters.")
    if len(set(password)) < 4:
        raise AuthError(422, "That is too easy to guess.")


def configured() -> bool:
    with session_scope() as s:
        return s.scalar(select(AdminAccount.id).limit(1)) is not None


_setup_code: str | None = None


def setup_code() -> str | None:
    """Required to set the first password; made and written only to the log, once
    per process, while there is no password.
    """
    global _setup_code
    if configured():
        _setup_code = None
        return None
    if _setup_code is None:
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        _setup_code = f"{raw[:4]}-{raw[4:]}"
        log.warning("admin setup code: %s (open /admin to set the admin password)", _setup_code)
    return _setup_code


def _same_code(typed: str, code: str) -> bool:
    clean = "".join(ch for ch in typed.upper() if ch.isalnum())
    return hmac.compare_digest(clean, code.replace("-", ""))


@dataclass
class _Misses:
    count: int = 0
    until: float = 0.0


_by_address: dict[str, _Misses] = {}
_recent: list[float] = []
_shut_until = 0.0


def _gate(address: str) -> None:
    now = time.monotonic()
    if _shut_until > now:
        raise AuthError(429, "Too many wrong passwords. Sign in is paused for a while.",
                        int(_shut_until - now) + 1)
    misses = _by_address.get(address)
    if misses and misses.until > now:
        raise AuthError(429, "Too many wrong passwords. Wait a moment and try again.",
                        int(misses.until - now) + 1)


def _missed(address: str) -> float:
    global _shut_until
    now = time.monotonic()
    misses = _by_address.setdefault(address, _Misses())
    misses.count += 1
    if misses.count >= PER_ADDRESS_FREE:
        wait = min(LONGEST_WAIT, FIRST_WAIT * 2 ** (misses.count - PER_ADDRESS_FREE))
        misses.until = now + wait
    _recent.append(now)
    while _recent and _recent[0] < now - GLOBAL_WINDOW:
        _recent.pop(0)
    if len(_recent) >= GLOBAL_MISSES:
        _shut_until = now + LONGEST_WAIT
        _recent.clear()
        log.warning("admin sign in paused: %d wrong passwords within the hour", GLOBAL_MISSES)
    return now


_lock = threading.Lock()


def _try(address: str) -> float:
    """Counted as a miss before the slow hash, not after: concurrent tries in the
    thread pool would otherwise all pass the gate. Returns the mark for _passed.
    """
    with _lock:
        _gate(address)
        return _missed(address)


def _passed(address: str, at: float | None = None) -> None:
    with _lock:
        _by_address.pop(address, None)
        if at is not None and at in _recent:
            _recent.remove(at)


def reset_throttle() -> None:
    global _shut_until
    _by_address.clear()
    _recent.clear()
    _shut_until = 0.0


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _open_session(ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with session_scope() as s:
        s.add(AdminSession(token_hash=_digest(token), created_at=now, last_seen_at=now,
                           expires_at=now + LIFETIME, ip=ip[:64], user_agent=user_agent[:255]))
        s.execute(delete(AdminSession).where(AdminSession.expires_at < now))
    return token


def set_up(code: str, password: str, ip: str, user_agent: str) -> str:
    at = _try(ip)
    expected = setup_code()
    if expected is None:
        _passed(ip, at)
        raise AuthError(409, "The admin password is already set.")
    if not _same_code(code, expected):
        raise AuthError(403, "That is not the setup code.")
    _passed(ip, at)
    check_strength(password)
    with session_scope() as s:
        s.add(AdminAccount(password_hash=hash_password(password)))
    global _setup_code
    _setup_code = None
    log.info("admin password set")
    return _open_session(ip, user_agent)


def sign_in(password: str, ip: str, user_agent: str) -> str:
    at = _try(ip)
    with session_scope() as s:
        account = s.scalar(select(AdminAccount).limit(1))
        stored = account.password_hash if account else None
    if stored is None:
        _passed(ip, at)
        raise AuthError(409, "No admin password yet. Set one first.")
    if not verify_password(stored, password):
        raise AuthError(403, "That is not the password.")
    _passed(ip, at)
    return _open_session(ip, user_agent)


def session_for(token: str | None) -> AdminSession | None:
    if not token:
        return None
    now = utcnow()
    with session_scope() as s:
        row = s.get(AdminSession, _digest(token))
        if row is None:
            return None
        if row.expires_at < now or row.last_seen_at + IDLE < now:
            s.delete(row)
            return None
        # Written at most once a minute, not on every request.
        if now - row.last_seen_at > timedelta(minutes=1):
            row.last_seen_at = now
        s.flush()
        s.expunge(row)
        return row


def sign_out(token: str | None) -> None:
    if not token:
        return
    with session_scope() as s:
        s.execute(delete(AdminSession).where(AdminSession.token_hash == _digest(token)))


def change_password(token: str, current: str, new: str, ip: str) -> None:
    at = _try(ip)
    with session_scope() as s:
        account = s.scalar(select(AdminAccount).limit(1))
        if account is None or not verify_password(account.password_hash, current):
            raise AuthError(403, "The current password is not right.")
        _passed(ip, at)
        check_strength(new)
        account.password_hash = hash_password(new)
        account.password_changed_at = utcnow()
        s.execute(delete(AdminSession).where(AdminSession.token_hash != _digest(token)))


def sessions(token: str) -> list[dict]:
    mine = _digest(token)
    with session_scope() as s:
        rows = s.scalars(select(AdminSession).order_by(AdminSession.last_seen_at.desc())).all()
        return [
            {
                "id": row.token_hash[:12],
                "current": row.token_hash == mine,
                "created_at": row.created_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "ip": row.ip,
                "user_agent": row.user_agent,
            }
            for row in rows
        ]


def end_session(public_id: str, token: str) -> None:
    if len(public_id) != 12 or _digest(token).startswith(public_id):
        raise AuthError(422, "Sign out of this browser with Sign out instead.")
    with session_scope() as s:
        for row in s.scalars(select(AdminSession)):
            if row.token_hash.startswith(public_id):
                s.delete(row)
