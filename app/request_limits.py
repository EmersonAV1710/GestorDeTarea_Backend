from datetime import datetime, timezone
from hashlib import sha256

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import RequestLimit, RevokedToken


def conflict_insert(db: Session, model):
    return sqlite_insert(model) if db.get_bind().dialect.name == "sqlite" else postgres_insert(model)


def enforce_request_limits(request: Request, db: Session = Depends(get_db)) -> None:
    # Keep logout available even after reaching a limit so the token can be revoked.
    if request.method == "OPTIONS" or request.url.path == "/api/auth/logout":
        return
    now = datetime.now(timezone.utc)
    window = int(now.timestamp()) // 60
    retry_after = max(1, (window + 1) * 60 - int(now.timestamp()))
    expires_at = datetime.fromtimestamp((window + 1) * 60, timezone.utc)
    ip = request.client.host if request.client else "unknown"
    budgets = [("api", settings.api_requests_per_minute)]
    if request.url.path == "/api/auth/login":
        budgets.append(("login", settings.login_requests_per_minute))
    elif request.url.path == "/api/auth/register":
        budgets.append(("register", settings.register_requests_per_minute))
    elif request.url.path == "/api/documents/analyze":
        budgets.append(("analysis", settings.analysis_requests_per_minute))
    db.execute(delete(RequestLimit).where(RequestLimit.expires_at <= now))
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
    for bucket, maximum in budgets:
        key = sha256(f"{ip}:{bucket}:{window}".encode()).hexdigest()
        statement = conflict_insert(db, RequestLimit).values(key=key, requests=1, expires_at=expires_at)
        statement = statement.on_conflict_do_update(index_elements=[RequestLimit.key], set_={"requests": RequestLimit.requests + 1}).returning(RequestLimit.requests)
        count = db.scalar(statement)
        if count > maximum:
            db.commit()
            raise HTTPException(429, "Se alcanzó el límite de solicitudes. Espera unos segundos e inténtalo de nuevo.", headers={"Retry-After": str(retry_after)})
    db.commit()
