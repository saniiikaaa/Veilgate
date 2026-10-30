"""Sign-in endpoints and the dependencies that protect the dashboard API."""

import time
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from src.core import auth
from src.core.config import get_settings
from src.core.scoring import raw_config
from src.repositories.db import _get_session_factory, set_tenant_context
from src.services import identity

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

_FAILS: dict[str, list[float]] = {}  # email -> recent failure times (in-memory throttle)


@dataclass(frozen=True)
class Account:
    principal_id: UUID
    email: str
    name: str
    role: str

    @property
    def scope(self) -> UUID | None:
        """Admins see every session; users see only their own."""
        return None if self.role == "admin" else self.principal_id


async def current_account(request: Request) -> Account:
    token = request.cookies.get(auth.COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    claims = auth.read_token(token) if token else None
    if not claims:
        raise HTTPException(401, "sign in required")
    return Account(UUID(claims["sub"]), claims["email"], claims.get("name", ""), claims["role"])


async def require_admin(acct: Account = Depends(current_account)) -> Account:
    if acct.role != "admin":
        raise HTTPException(403, "admin only")
    return acct


async def ensure_demo_accounts() -> None:
    """Create the demo logins from config/default.yml if they are missing."""
    settings = get_settings()
    is_production = settings.is_production
    admin_email = settings.bootstrap_admin_email.strip().lower()
    admin_password = settings.bootstrap_admin_password
    if is_production and bool(admin_email) != bool(admin_password):
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set together")
    demo_accounts = [] if is_production else raw_config().get("auth", {}).get("demo_accounts", [])
    if not demo_accounts and not admin_email:
        return

    tenant = UUID(settings.default_tenant_id)
    async with _get_session_factory()() as db:
        await set_tenant_context(db, tenant)
        for a in demo_accounts:
            uid = await identity.get_or_create_user(db, tenant, a["user_key"])
            await db.execute(
                text(
                    "INSERT INTO auth_accounts (principal_id, tenant_id, email, password_hash, role) "
                    "VALUES (:p, :t, :e, :h, :r) ON CONFLICT (email) DO NOTHING"
                ),
                {"p": uid, "t": tenant, "e": a["email"].lower(), "h": auth.hash_password(a["password"]), "r": a["role"]},
            )
        if admin_email:
            uid = await identity.get_or_create_user(db, tenant, admin_email)
            await db.execute(
                text(
                    "INSERT INTO auth_accounts (principal_id, tenant_id, email, password_hash, role) "
                    "VALUES (:p, :t, :e, :h, 'admin') ON CONFLICT (email) DO NOTHING"
                ),
                {"p": uid, "t": tenant, "e": admin_email, "h": auth.hash_password(admin_password)},
            )
        await db.commit()


class LoginIn(BaseModel):
    email: str
    password: str


def _public(a: Account) -> dict:
    return {"email": a.email, "name": a.name, "role": a.role}


@auth_router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    email = body.email.strip().lower()
    now = time.time()
    recent = [t for t in _FAILS.get(email, []) if now - t < 300]
    if len(recent) >= 5:
        raise HTTPException(429, "too many attempts, try again in a few minutes")
    async with _get_session_factory()() as db:
        account = (await db.execute(
            text("SELECT principal_id, tenant_id, password_hash, role, email FROM auth_accounts WHERE email = :e"),
            {"e": email},
        )).mappings().first()
        row = None
        if account:
            await set_tenant_context(db, account["tenant_id"])
            user = (await db.execute(
                text("SELECT name FROM users WHERE principal_id = :p"),
                {"p": account["principal_id"]},
            )).mappings().first()
            if user:
                row = {
                    **account,
                    "name": user["name"] or account["email"],
                }
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        _FAILS[email] = [*recent, now]
        raise HTTPException(401, "wrong email or password")
    _FAILS.pop(email, None)
    hours = int(raw_config().get("auth", {}).get("session_hours", 8))
    acct = Account(row["principal_id"], email, row["name"], row["role"])
    token = auth.make_token({"sub": str(acct.principal_id), "email": email, "name": acct.name, "role": acct.role}, hours * 3600)
    response.set_cookie(
        auth.COOKIE,
        token,
        max_age=hours * 3600,
        httponly=True,
        samesite="lax",
        secure=get_settings().is_production,
        path="/",
    )
    return _public(acct)


@auth_router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE, path="/", secure=get_settings().is_production)
    return {"ok": True}


@auth_router.get("/status")
async def status(request: Request) -> dict:
    """Like /me, but answers 200 either way, so the public landing page can check quietly."""
    token = request.cookies.get(auth.COOKIE)
    claims = auth.read_token(token) if token else None
    return {"signed_in": bool(claims), "name": (claims or {}).get("name"), "role": (claims or {}).get("role")}


@auth_router.get("/me")
async def me(acct: Account = Depends(current_account)) -> dict:
    return _public(acct)


@auth_router.get("/demo")
async def demo_hint() -> list[dict]:
    """Demo logins for the sign-in page (only when show_demo_hint is true in config)."""
    cfg = raw_config().get("auth", {})
    if get_settings().is_production or not cfg.get("show_demo_hint"):
        return []
    return [{"email": a["email"], "password": a["password"], "role": a["role"], "name": a["name"]} for a in cfg.get("demo_accounts", [])]


# ---------------------------------------------------------------------------------------------------------------------
# public live demo for the landing page: no sign-in, nothing stored, no model called, throttled per client
# ---------------------------------------------------------------------------------------------------------------------
_PUBLIC_HITS: dict[str, list[float]] = {}


class PublicDetectIn(BaseModel):
    text: str


@auth_router.post("/public-detect")
async def public_detect(body: PublicDetectIn, request: Request) -> dict:
    from src.detection import detect, find_injection
    from src.services.hooks import get_crypto

    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = [t for t in _PUBLIC_HITS.get(ip, []) if now - t < 60]
    if len(hits) >= 40:
        raise HTTPException(429, "slow down a little")
    _PUBLIC_HITS[ip] = [*hits, now]
    text_in = body.text[:1500]
    crypto, tenant = get_crypto(), UUID(get_settings().default_tenant_id)
    out, pos, items = [], 0, []
    for e in detect(text_in):
        tok = crypto.token(e.type, crypto.value_hmac(tenant, e.type, e.value))
        out += [text_in[pos:e.start], tok]
        pos = e.end
        items.append({"type": e.type, "start": e.start, "end": e.end, "value": e.value, "token": tok})
    return {"masked": "".join(out) + text_in[pos:], "entities": items, "injection": find_injection(text_in)}
