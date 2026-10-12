"""Activity types round-trip through HTTP using only an in-memory database."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app, current_user
from app.models import User, Course, Document, Activity


@pytest.fixture
def api():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id=uuid4(), email="test@example.invalid", username="test", password_hash="unused")
        course = Course(id=uuid4(), user_id=owner.id, name="Prueba")
        document = Document(id=uuid4(), user_id=owner.id, course_id=course.id, filename="prueba.txt")
        db.add_all([owner, course, document])
        db.commit()
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[current_user] = lambda: owner
        try:
            with TestClient(app) as client:
                yield client, db, owner, course, document
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
    engine.dispose()


@pytest.mark.parametrize("activity_type", ["tarea", "proyecto", "examen", "exposicion", "laboratorio", "lectura", "otro"])
def test_confirmation_preserves_the_type_and_remains_idempotent(api, activity_type):
    client, db, _, _, document = api
    body = {"document_id": str(document.id), "activities": [{"title": "Entrega",
            "activity_type": activity_type, "due_date": "2026-11-20"}]}

    response = client.post("/api/activities/confirm", json=body)

    assert response.status_code == 200
    assert response.json()[0]["activity_type"] == activity_type
    assert db.scalar(select(Activity)).activity_type == activity_type
    assert client.post("/api/activities/confirm", json=body).json() == response.json()
    assert db.scalar(select(func.count()).select_from(Activity)) == 1


def test_confirmation_can_save_past_proposals_as_overdue_or_delivered(api):
    client, db, _, _, document = api
    body = {"document_id": str(document.id), "activities": [
        {"title": "Vencida", "due_date": "2020-01-01", "status": "pending"},
        {"title": "Entregada", "due_date": "2020-01-02", "status": "completed"},
    ]}

    response = client.post("/api/activities/confirm", json=body)

    assert response.status_code == 200
    assert [activity["status"] for activity in response.json()] == ["pending", "completed"]
    saved = {activity.title: activity for activity in db.scalars(select(Activity))}
    assert saved["Vencida"].completed_at is None
    assert saved["Entregada"].completed_at is not None


def test_confirmation_rejects_an_unknown_status(api):
    client, db, _, _, document = api
    response = client.post("/api/activities/confirm", json={"document_id": str(document.id),
        "activities": [{"title": "Entrega", "status": "expired"}]})
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(Activity)) == 0


def test_filters_combine_type_course_and_dates_and_keep_owner_isolation(api):
    client, db, owner, course, _ = api
    other = User(id=uuid4(), email="other@example.invalid", username="other", password_hash="unused")
    other_course = Course(id=uuid4(), user_id=other.id, name="Ajeno")
    db.add_all([other, other_course])
    expected = Activity(id=uuid4(), user_id=owner.id, course_id=course.id, title="Examen propio",
                        activity_type="examen", due_date=date(2026, 11, 20))
    db.add_all([expected,
        Activity(user_id=owner.id, course_id=course.id, title="Tarea", activity_type="tarea", due_date=date(2026, 11, 20)),
        Activity(user_id=owner.id, course_id=course.id, title="Examen fuera de fecha", activity_type="examen", due_date=date(2026, 12, 1)),
        Activity(user_id=other.id, course_id=other_course.id, title="Examen ajeno", activity_type="examen", due_date=date(2026, 11, 20)),
    ])
    db.commit()

    response = client.get("/api/activities", params={"activity_type": "examen", "course_id": str(course.id),
                         "date_from": "2026-11-20", "date_to": "2026-11-20"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(expected.id)]
    assert len(client.get("/api/activities").json()) == 3


def test_invalid_types_are_rejected_and_missing_types_remain_compatible(api):
    client, db, _, _, document = api
    body = {"document_id": str(document.id), "activities": [{"title": "Entrega", "activity_type": "invalido"}]}

    assert client.post("/api/activities/confirm", json=body).status_code == 422
    assert client.get("/api/activities", params={"activity_type": "invalido"}).status_code == 422
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    body["activities"][0].pop("activity_type")
    response = client.post("/api/activities/confirm", json=body)
    assert response.status_code == 200
    assert response.json()[0]["activity_type"] == "otro"
    assert client.get("/api/activities", params={"activity_type": "otro"}).json() == response.json()
