"""Who is calling the API? Verifies the Supabase login token sent by the website.

The website logs users in with Supabase Auth and sends the token in the header
    Authorization: Bearer <token>
We verify the token's signature with Supabase's PUBLIC keys (JWKS), check it is
not expired and was issued by our project, then load the user's profile.
"""
from dataclasses import dataclass
from typing import Optional

import jwt
import psycopg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app import config
from app.db import get_conn

ASYMMETRIC_ALGORITHMS = ("ES256", "RS256", "EdDSA")
bearer = HTTPBearer(auto_error=False)
_jwks_client: Optional[PyJWKClient] = None


@dataclass
class CurrentUser:
    id: str
    email: Optional[str]
    full_name: Optional[str]
    role: str                      # candidate / employer / admin
    privacy_consent_at: Optional[object]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not config.SUPABASE_URL:
            raise RuntimeError("SUPABASE_URL is not set. Add it to the .env file.")
        _jwks_client = PyJWKClient(f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
                                   cache_keys=True, lifespan=600)
    return _jwks_client


def _signing_key(token: str, alg: str):
    if alg in ASYMMETRIC_ALGORITHMS:
        return _jwks().get_signing_key_from_jwt(token).key
    if alg == "HS256" and config.SUPABASE_JWT_SECRET:
        return config.SUPABASE_JWT_SECRET
    raise jwt.InvalidTokenError(f"unsupported token algorithm {alg}")


def decode_token(token: str) -> dict:
    """Verify signature, expiry, audience and issuer. Raises jwt.InvalidTokenError."""
    alg = jwt.get_unverified_header(token).get("alg", "")
    return jwt.decode(
        token,
        _signing_key(token, alg),
        algorithms=[alg],
        audience="authenticated",
        issuer=f"{config.SUPABASE_URL}/auth/v1",
        options={"require": ["exp", "sub", "aud", "iss"]},
        leeway=30,
    )


def _load_user(conn: psycopg.Connection, claims: dict) -> CurrentUser:
    row = conn.execute(
        "select id::text, full_name, role, is_blocked, privacy_consent_at from public.profiles where id = %s",
        (claims["sub"],)).fetchone()
    if row is None:
        raise _unauthorized("Account not found")
    if row[3]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been blocked")
    return CurrentUser(id=row[0], email=claims.get("email"), full_name=row[1], role=row[2],
                       privacy_consent_at=row[4])


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    conn: psycopg.Connection = Depends(get_conn),
) -> CurrentUser:
    """For endpoints that REQUIRE login."""
    if creds is None:
        raise _unauthorized("Login required")
    try:
        claims = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired login. Please log in again.")
    return _load_user(conn, claims)


def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    conn: psycopg.Connection = Depends(get_conn),
) -> Optional[CurrentUser]:
    """For endpoints that work for guests too (user is None for guests)."""
    if creds is None:
        return None
    return get_current_user(creds, conn)


def require_role(*roles: str):
    """Dependency factory: only users with one of these roles may call the endpoint."""
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this")
        return user
    return checker
