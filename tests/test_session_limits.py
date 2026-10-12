from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select, func

from app.config import settings
from app.main import app, current_user
from app.models import RequestLimit, RevokedToken
from app.security import token_for, token_digest
from test_activity_types import api


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_only_the_current_token_and_new_sessions_are_unique(api):
    client, db, owner, _, _ = api
    app.dependency_overrides.pop(current_user)
    first, second = token_for(str(owner.id)), token_for(str(owner.id))
    assert first != second
    assert client.get("/api/courses", headers=headers(first)).status_code == 200
    assert client.post("/api/auth/logout", headers=headers(first)).status_code == 204
    assert db.get(RevokedToken, token_digest(first)) is not None
    assert client.get("/api/courses", headers=headers(first)).status_code == 401
    assert client.get("/api/courses", headers=headers(second)).status_code == 200
    with TestClient(app) as another_client:
        assert another_client.get("/api/documents/pending", headers=headers(first)).status_code == 401


def test_preexisting_tokens_can_also_be_revoked(api):
    client, _, owner, _, _ = api
    app.dependency_overrides.pop(current_user)
    legacy = jwt.encode({"sub": str(owner.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.jwt_secret, algorithm="HS256")
    assert client.post("/api/auth/logout", headers=headers(legacy)).status_code == 204
    assert client.get("/api/activities", headers=headers(legacy)).status_code == 401


def test_logout_requires_valid_authentication(api):
    client, _, _, _, _ = api
    app.dependency_overrides.pop(current_user)
    assert client.post("/api/auth/logout").status_code == 401
    assert client.post("/api/auth/logout", headers=headers("invalid")).status_code == 401


def test_global_ip_limit_returns_retry_after_and_cannot_be_bypassed_with_forwarded_header(api, monkeypatch):
    client, _, _, _, _ = api
    monkeypatch.setattr(settings, "api_requests_per_minute", 2)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    limited = client.get("/api/health")
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    assert client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.123"}).status_code == 429
    with TestClient(app, client=("198.51.100.2", 50000)) as another_ip:
        assert another_ip.get("/api/health").status_code == 200


@pytest.mark.parametrize("path,setting", [("/api/auth/login", "login_requests_per_minute"),
    ("/api/auth/register", "register_requests_per_minute"), ("/api/documents/analyze", "analysis_requests_per_minute")])
def test_sensitive_routes_have_their_own_ip_budget_before_validation(api, monkeypatch, path, setting):
    client, _, _, _, _ = api
    monkeypatch.setattr(settings, setting, 1)
    assert client.post(path, json={}).status_code == 422
    assert client.post(path, json={}).status_code == 429
    assert client.get("/api/health").status_code == 200


def test_logout_remains_available_after_hitting_the_global_limit(api, monkeypatch):
    client, _, owner, _, _ = api
    app.dependency_overrides.pop(current_user)
    monkeypatch.setattr(settings, "api_requests_per_minute", 1)
    token = token_for(str(owner.id))
    assert client.get("/api/courses", headers=headers(token)).status_code == 200
    assert client.get("/api/courses", headers=headers(token)).status_code == 429
    assert client.post("/api/auth/logout", headers=headers(token)).status_code == 204


def test_rate_windows_expire_and_old_records_are_removed(api, monkeypatch):
    client, db, _, _, _ = api
    import app.request_limits as limits
    now = datetime.now(timezone.utc)
    class Clock:
        @staticmethod
        def now(tz):
            return now
        @staticmethod
        def fromtimestamp(value, tz):
            return datetime.fromtimestamp(value, tz)
    monkeypatch.setattr(limits, "datetime", Clock)
    monkeypatch.setattr(settings, "api_requests_per_minute", 1)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 429
    now += timedelta(seconds=61)
    assert client.get("/api/health").status_code == 200
    assert db.scalar(select(func.count()).select_from(RequestLimit)) == 1


def test_tokens_without_expiration_are_rejected(api):
    client, _, owner, _, _ = api
    app.dependency_overrides.pop(current_user)
    token = jwt.encode({"sub": str(owner.id)}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/courses", headers=headers(token)).status_code == 401
