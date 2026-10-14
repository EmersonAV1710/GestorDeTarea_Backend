from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import select, func

from app.config import settings
from app.main import app, current_user
from app.models import Course, User
from app.security import hash_password, verify_password
from test_activity_types import api


def test_passwords_use_argon2id_and_distinct_salts():
    first = hash_password("Clave8ok")
    second = hash_password("Clave8ok")
    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password("Clave8ok", first)
    assert not verify_password("OtraClave9", first)


@pytest.mark.parametrize("method,path", [("GET", "/api/courses"), ("GET", "/api/activities"),
    ("GET", "/api/documents/pending"), ("DELETE", "/api/documents/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), ("POST", "/api/courses"),
    ("PATCH", "/api/activities/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    ("DELETE", "/api/activities/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")])
def test_private_routes_reject_missing_tokens(api, method, path):
    client, _, _, _, _ = api
    app.dependency_overrides.pop(current_user)
    assert client.request(method, path, json={"name": "Curso", "title": "Entrega"}).status_code == 401


def test_document_analysis_rejects_guest_upload_before_processing(api):
    client, _, _, course, _ = api
    app.dependency_overrides.pop(current_user)
    response = client.post("/api/documents/analyze", data={"course_id": str(course.id)},
                           files={"file": ("sample.txt", b"A private task", "text/plain")})
    assert response.status_code == 401


@pytest.mark.parametrize("kind", ["expired", "forged", "deleted-user"])
def test_private_routes_reject_invalid_tokens(api, kind):
    client, _, owner, _, _ = api
    app.dependency_overrides.pop(current_user)
    payload = {"sub": str(uuid4()) if kind == "deleted-user" else str(owner.id),
               "exp": datetime.now(timezone.utc) + timedelta(hours=-1 if kind == "expired" else 1)}
    token = jwt.encode(payload, "attacker-key" if kind == "forged" else settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/documents/pending", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_sql_payload_is_stored_as_text_without_executing_statements(api):
    client, db, _, _, _ = api
    payload = "'; DROP TABLE courses; --"
    response = client.post("/api/courses", json={"name": payload})
    assert response.status_code == 201
    assert response.json()["name"] == payload
    assert db.scalar(select(func.count()).select_from(Course)) == 2
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_three_failed_logins_lock_the_account_and_expired_lock_can_be_reset(api):
    client, db, owner, _, _ = api
    owner.password_hash = hash_password("Clave8ok")
    db.commit()
    for expected in (401, 401, 429):
        assert client.post("/api/auth/login", json={"username": owner.username, "password": "Incorrecta9"}).status_code == expected
    assert client.post("/api/auth/login", json={"username": owner.username, "password": "Clave8ok"}).status_code == 429
    owner.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.post("/api/auth/login", json={"username": owner.username, "password": "Clave8ok"}).status_code == 200
    db.refresh(owner)
    assert owner.failed_login_attempts == 0
    assert owner.locked_until is None
