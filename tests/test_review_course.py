"""A pending review can move courses before its activities are confirmed."""
from uuid import uuid4

from sqlalchemy import select

from app.models import Activity, Course, Document, User
from test_activity_types import api


def test_move_review_persists_and_confirmation_uses_new_course(api):
    client, db, owner, original, document = api
    target = Course(id=uuid4(), user_id=owner.id, name="Curso destino")
    db.add(target)
    db.commit()

    moved = client.patch(f"/api/documents/{document.id}", json={"course_id": str(target.id)})
    assert moved.status_code == 200
    assert moved.json()["course_id"] == str(target.id)
    assert client.get("/api/documents/pending").json()[0]["course_id"] == str(target.id)

    confirmed = client.post("/api/activities/confirm", json={
        "document_id": str(document.id), "activities": [{"title": "Entrega", "due_date": None}],
    })
    assert confirmed.status_code == 200
    assert confirmed.json()[0]["course_id"] == str(target.id)
    assert db.scalar(select(Activity)).course_id == target.id
    assert db.get(Document, document.id).course_id == target.id
    assert original.id != target.id


def test_move_review_rejects_foreign_inactive_and_confirmed_resources(api):
    client, db, owner, original, document = api
    other = User(id=uuid4(), email="other@example.invalid", username="other", password_hash="unused")
    foreign = Course(id=uuid4(), user_id=other.id, name="Ajeno")
    inactive = Course(id=uuid4(), user_id=owner.id, name="Inactivo", is_active=False)
    db.add_all([other, foreign, inactive])
    db.commit()

    path = f"/api/documents/{document.id}"
    assert client.patch(path, json={"course_id": str(foreign.id)}).status_code == 404
    assert client.patch(path, json={"course_id": str(inactive.id)}).status_code == 409
    assert db.get(Document, document.id).course_id == original.id

    document.is_confirmed = True
    db.commit()
    assert client.patch(path, json={"course_id": str(original.id)}).status_code == 409
    assert client.patch(f"/api/documents/{uuid4()}", json={"course_id": str(original.id)}).status_code == 404
