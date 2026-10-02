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
        owner = User(email=f"pytest-{suffix}@example.invalid", password_hash=hash_password(TEST_PASSWORD))
        other = User(email=f"pytest-other-{suffix}@example.invalid", password_hash=hash_password(TEST_PASSWORD))
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
    response = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_rejects_bad_password_and_private_routes_require_auth(accounts):
    owner, _, _, _ = accounts
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "incorrecta"}).status_code == 401
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
