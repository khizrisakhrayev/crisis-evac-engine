"""Staff authentication: PBKDF2 password hashes + HS256 JWTs (PyJWT)."""
import hashlib
import hmac
import os
import time

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import User


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, config.PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${config.PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def create_token(username: str, role: str, expires_s: int | None = None) -> str:
    now = int(time.time())
    exp = now + (config.JWT_EXPIRES_S if expires_s is None else expires_s)
    return jwt.encode({"sub": username, "role": role, "iat": now, "exp": exp},
                      config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Claims of a valid token, else None (expired, tampered, malformed)."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    return user if user and verify_password(password, user.password_hash) else None


def seed_users(db: Session) -> None:
    """Create or update the staff accounts from config.STAFF_USERS (passwords from env)."""
    for username, (role, password) in config.STAFF_USERS.items():
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username, role=role, password_hash=hash_password(password)))
        elif not verify_password(password, user.password_hash) or user.role != role:
            user.role, user.password_hash = role, hash_password(password)
    db.commit()
