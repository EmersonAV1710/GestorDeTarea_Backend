from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Activity, Course, Document, User
from app.security import hash_password

client = TestClient(app)
TEST_PASSWORD = "ClaveTemporalDePruebas-2026!"


@pytest.fixture
def accounts():
    """Create disposable users/courses and remove them after each integration test."""
    suffix = uuid4().hex
    with SessionLocal() as db:
        owner = User(email=f"pytest-{suffix}@example.invalid", username=f"pytest_{suffix[:12]}", password_hash=hash_password(TEST_PASSWORD))
        other = User(email=f"pytest-other-{suffix}@example.invalid", username=f"other_{suffix[:12]}", password_hash=hash_password(TEST_PASSWORD))
        db.add_all([owner, other])
        db.flush()
        course = Course(user_id=owner.id, name=f"Curso {suffix}")
        other_course = Course(user_id=other.id, name=f"Curso ajeno {suffix}")
        db.add_all([course, other_course])
        db.commit()
        db.refresh(owner)
        db.refresh(other)
        db.refresh(course)
        db.refresh(other_course)
        try:
            yield owner, course, other, other_course
        finally:
            db.delete(owner)
            db.delete(other)
            db.commit()


def auth(user: User) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": user.username, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_rejects_bad_password_and_private_routes_require_auth(accounts):
    owner, _, _, _ = accounts
    assert client.post("/api/auth/login", json={"username": owner.username, "password": "incorrecta"}).status_code == 401
    assert client.get("/api/courses").status_code == 401
    assert client.get("/api/courses", headers=auth(owner)).status_code == 200


def test_courses_and_documents_are_scoped_to_owner(accounts):
    owner, own_course, _, other_course = accounts
    headers = auth(owner)
    courses = client.get("/api/courses", headers=headers)
    assert courses.status_code == 200
    assert [item["id"] for item in courses.json()] == [str(own_course.id)]
    response = client.post(
        "/api/documents/analyze",
        headers=headers,
        data={"course_id": str(other_course.id)},
        files={"file": ("sample.pdf", b"not read because the course is unauthorized", "application/pdf")},
    )
    assert response.status_code == 404


def test_course_edit_deactivation_and_reactivation_preserve_history(accounts):
    owner, course, _, other_course = accounts
    headers = auth(owner)
    with SessionLocal() as db:
        activity = Activity(user_id=owner.id, course_id=course.id, title="Entrega conservada")
        document = Document(user_id=owner.id, course_id=course.id, filename="programa.pdf", status="analyzed")
        db.add_all([activity, document])
        db.commit()
        activity_id, document_id = activity.id, document.id

    assert client.patch(f"/api/courses/{other_course.id}", headers=headers, json={"name": "Ajeno"}).status_code == 404
    assert client.delete(f"/api/courses/{other_course.id}", headers=headers).status_code == 404
    assert client.patch(f"/api/courses/{other_course.id}/activate", headers=headers).status_code == 404

    renamed = client.patch(
        f"/api/courses/{course.id}", headers=headers,
        json={"name": "  Matemática avanzada  ", "code": " MAT-2 ", "term": " 2026-II "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Matemática avanzada"
    assert renamed.json()["code"] == "MAT-2"
    assert renamed.json()["term"] == "2026-II"
    assert renamed.json()["is_active"] is True

    inactive = client.delete(f"/api/courses/{course.id}", headers=headers)
    assert inactive.status_code == 200 and inactive.json()["is_active"] is False
    listed = client.get("/api/courses", headers=headers).json()
    assert listed[0]["id"] == str(course.id) and listed[0]["is_active"] is False
    with SessionLocal() as db:
        assert db.get(Activity, activity_id) is not None
        assert db.get(Document, document_id) is not None

    upload = client.post(
        "/api/documents/analyze", headers=headers, data={"course_id": str(course.id)},
        files={"file": ("programa.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert upload.status_code == 409
    assert "inactivo" in upload.json()["detail"]
    active = client.patch(f"/api/courses/{course.id}/activate", headers=headers)
    assert active.status_code == 200 and active.json()["is_active"] is True


def test_course_name_validation_and_duplicate_edit(accounts):
    owner, course, _, _ = accounts
    headers = auth(owner)
    another = client.post("/api/courses", headers=headers, json={"name": "Otro curso"})
    assert another.status_code == 201
    assert client.post("/api/courses", headers=headers, json={"name": "   "}).status_code == 422
    assert client.patch(f"/api/courses/{course.id}", headers=headers, json={"name": "   "}).status_code == 422
    duplicate = client.patch(f"/api/courses/{course.id}", headers=headers, json={"name": "Otro curso"})
    assert duplicate.status_code == 409
    with SessionLocal() as db:
        assert db.get(Course, course.id).name == course.name


def test_date_filters_upcoming_order_and_completion_persist(accounts):
    owner, course, _, _ = accounts
    headers = auth(owner)
    today = date.today()
    first = Activity(user_id=owner.id, course_id=course.id, title="Próxima 1", due_date=today + timedelta(days=1))
    second = Activity(user_id=owner.id, course_id=course.id, title="Próxima 2", due_date=today + timedelta(days=2))
    completed = Activity(user_id=owner.id, course_id=course.id, title="Ya completada", due_date=today + timedelta(days=1), status="completed")
    no_date = Activity(user_id=owner.id, course_id=course.id, title="Sin fecha", due_date=None)
    with SessionLocal() as db:
        db.add_all([first, second, completed, no_date])
        db.commit()
        ids = {name: value.id for name, value in [("first", first), ("second", second)]}
    upcoming = client.get("/api/activities?upcoming=true", headers=headers)
    assert [item["title"] for item in upcoming.json()] == ["Próxima 1", "Próxima 2"]
    filtered = client.get(
        f"/api/activities?date_from={today + timedelta(days=1)}&date_to={today + timedelta(days=1)}",
        headers=headers,
    )
    assert {item["title"] for item in filtered.json()} == {"Próxima 1", "Ya completada"}
    response = client.patch(f"/api/activities/{ids['first']}/complete", headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "completed"
    again = client.get("/api/activities", headers=headers)
    assert next(item for item in again.json() if item["id"] == str(ids["first"]))["status"] == "completed"


def test_confirming_same_document_twice_does_not_duplicate(accounts):
    owner, course, _, _ = accounts
    headers = auth(owner)
    with SessionLocal() as db:
        document = Document(user_id=owner.id, course_id=course.id, filename="documento-de-prueba.pdf", status="analyzed")
        db.add(document)
        db.commit()
        db.refresh(document)
        document_id = str(document.id)
    payload = {
        "document_id": document_id,
        "activities": [{"title": "Actividad revisada", "description": "Dato de prueba", "due_date": None, "review_required": True}],
    }
    first = client.post("/api/activities/confirm", headers=headers, json=payload)
    second = client.post("/api/activities/confirm", headers=headers, json=payload)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()[0]["id"] == second.json()[0]["id"]
    with SessionLocal() as db:
        count = len(list(db.scalars(select(Activity).where(Activity.document_id == document_id))))
    assert count == 1


def _searchable_pdf(text: str) -> bytes:
    """Build a tiny PDF fixture without storing a real course document."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode("ascii"))
        result.extend(obj)
        result.extend(b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(result)


def test_pdf_without_ai_key_returns_clear_error_and_no_fake_proposals(accounts, monkeypatch):
    owner, course, _, _ = accounts
    monkeypatch.setattr("app.main.settings.gemini_api_key", "")
    response = client.post(
        "/api/documents/analyze",
        headers=auth(owner),
        data={"course_id": str(course.id)},
        files={"file": ("programa-sintetico.pdf", _searchable_pdf("Actividad y fecha 20 de noviembre"), "application/pdf")},
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert "propuestas" in response.json()["detail"]


def test_upload_rejects_unsupported_and_unreadable_content(accounts):
    owner, course, _, _ = accounts
    headers = auth(owner)
    wrong_type = client.post(
        "/api/documents/analyze",
        headers=headers,
        data={"course_id": str(course.id)},
        files={"file": ("imagen.png", b"imagen", "image/png")},
    )
    assert wrong_type.status_code == 415
    unreadable = client.post(
        "/api/documents/analyze",
        headers=headers,
        data={"course_id": str(course.id)},
        files={"file": ("nota.pdf", b"contenido que no es un PDF", "application/pdf")},
    )
    assert unreadable.status_code == 422


def test_registration_validates_password_and_creates_argon2_account():
    email = f"register-{uuid4().hex}@example.invalid"
    username = f"register_{uuid4().hex[:12]}"
    minimum_password = "Clave8ok"
    weak = client.post("/api/auth/register", json={"email": email, "username":username,"password": "corta12", "password_confirmation": "corta12"})
    assert weak.status_code == 422
    invalid_username = client.post("/api/auth/register", json={"email": email, "username":"usuario con espacios","password": minimum_password, "password_confirmation": minimum_password})
    assert invalid_username.status_code == 422
    mismatch = client.post("/api/auth/register", json={"email": email, "username":username,"password": minimum_password, "password_confirmation": "OtraClaveTemporal-2026!"})
    assert mismatch.status_code == 422
    created = client.post("/api/auth/register", json={"email": email.upper(), "username":username.upper(),"password": minimum_password, "password_confirmation": minimum_password})
    assert created.status_code == 201
    duplicate = client.post("/api/auth/register", json={"email": email, "username":username,"password": minimum_password, "password_confirmation": minimum_password})
    assert duplicate.status_code == 409
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None and user.username == username and user.password_hash != minimum_password
        db.delete(user)
        db.commit()


def test_login_locks_after_three_failures_and_success_resets_counter(accounts):
    owner, _, _, _ = accounts
    for remaining in (2, 1):
        response = client.post("/api/auth/login", json={"username": owner.username, "password": "contraseña incorrecta"})
        assert response.status_code == 401
        assert f"{remaining} intento(s)" in response.json()["detail"]
    locked = client.post("/api/auth/login", json={"username": owner.username, "password": "contraseña incorrecta"})
    assert locked.status_code == 429
    assert "15 minutos" in locked.json()["detail"]
    still_locked = client.post("/api/auth/login", json={"username": owner.username, "password": TEST_PASSWORD})
    assert still_locked.status_code == 429
    with SessionLocal() as db:
        user = db.get(User, owner.id)
        user.locked_until = None
        user.failed_login_attempts = 2
        db.commit()
    good = client.post("/api/auth/login", json={"username": owner.username, "password": TEST_PASSWORD})
    assert good.status_code == 200
    with SessionLocal() as db:
        user = db.get(User, owner.id)
        assert user.failed_login_attempts == 0 and user.locked_until is None
