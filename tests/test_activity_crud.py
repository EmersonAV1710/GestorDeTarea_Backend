from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.main import app, current_user
from app.models import Activity, Course, Document, User
from test_activity_types import api


def add_activity(api):
    _, db, owner, course, document = api
    activity = Activity(id=uuid4(), user_id=owner.id, course_id=course.id, document_id=document.id,
                        title="Tarea original", description="Descripción", activity_type="tarea", due_date=date(2026, 11, 20))
    db.add(activity)
    db.commit()
    return activity


def test_manual_activity_is_saved_without_a_document(api):
    client, db, _, course, _ = api
    response = client.post("/api/activities", json={"course_id": str(course.id), "title": "  Entrega manual  ",
        "description": "Preparar el informe", "activity_type": "tarea", "due_date": "2026-11-20"})

    assert response.status_code == 201
    assert response.json()["title"] == "Entrega manual"
    assert response.json()["document_id"] is None
    assert response.json()["status"] == "pending"
    assert db.get(Activity, UUID(response.json()["id"])).document_id is None


def test_empty_course_can_be_deleted_with_its_pending_documents(api):
    client, db, _, course, document = api

    response = client.delete(f"/api/courses/{course.id}/permanent")

    assert response.status_code == 204
    assert db.get(Course, course.id) is None
    assert db.get(Document, document.id) is None
    assert client.get("/api/courses").json() == []


def test_course_with_activities_can_only_be_deactivated(api):
    client, db, _, course, document = api
    activity = add_activity(api)

    response = client.delete(f"/api/courses/{course.id}/permanent")

    assert response.status_code == 409
    assert db.get(Course, course.id) is not None
    assert db.get(Activity, activity.id) is not None
    assert db.get(Document, document.id) is not None
    assert client.delete(f"/api/courses/{course.id}").json()["is_active"] is False
    assert db.get(Activity, activity.id) is not None


def test_cannot_delete_another_users_empty_course(api):
    client, db, _, _, _ = api
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    foreign = Course(id=uuid4(), user_id=other.id, name="Ajeno")
    db.add_all([other, foreign])
    db.commit()

    assert client.delete(f"/api/courses/{foreign.id}/permanent").status_code == 404
    assert db.get(Course, foreign.id) is not None


def test_manual_activity_can_be_created_as_completed(api):
    client, db, _, course, _ = api
    response = client.post("/api/activities", json={"course_id": str(course.id), "title": "Trabajo entregado",
        "due_date": "2020-01-01", "status": "completed"})
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert db.get(Activity, UUID(response.json()["id"])).completed_at is not None


def test_manual_activity_rejects_duplicate_inactive_or_foreign_course(api):
    client, db, owner, course, _ = api
    body = {"course_id": str(course.id), "title": "Entrega", "due_date": "2026-11-20"}
    assert client.post("/api/activities", json=body).status_code == 201
    assert client.post("/api/activities", json=body).status_code == 409
    course.is_active = False
    db.commit()
    assert client.post("/api/activities", json={**body, "title": "Otra"}).status_code == 409
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    foreign = Course(id=uuid4(), user_id=other.id, name="Ajeno")
    db.add_all([other, foreign])
    db.commit()
    assert client.post("/api/activities", json={**body, "course_id": str(foreign.id)}).status_code == 404


@pytest.mark.parametrize("changes", [{"title": " "}, {"due_date": "2026-02-30"},
                                     {"activity_type": "invalido"}, {"status": "expired"},
                                     {"document_id": str(uuid4())}])
def test_manual_activity_rejects_invalid_fields(api, changes):
    client, db, _, course, _ = api
    response = client.post("/api/activities", json={"course_id": str(course.id), "title": "Entrega", **changes})
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(Activity)) == 0


def test_edit_persists_fields_and_keeps_the_owner_course_document_and_status(api):
    client, db, owner, course, document = api
    activity = add_activity(api)
    client.patch(f"/api/activities/{activity.id}/complete")
    completed_at = activity.completed_at

    response = client.patch(f"/api/activities/{activity.id}", json={"title": "  Proyecto corregido  ",
        "description": "Nuevos detalles", "activity_type": "proyecto", "due_date": None, "review_required": False})

    assert response.status_code == 200
    assert response.json()["title"] == "Proyecto corregido"
    assert response.json()["activity_type"] == "proyecto"
    assert response.json()["review_required"] is True
    db.refresh(activity)
    assert activity.description == "Nuevos detalles"
    assert activity.due_date is None
    assert activity.status == "completed"
    assert activity.completed_at == completed_at
    assert activity.user_id == owner.id
    assert activity.course_id == course.id
    assert activity.document_id == document.id


def test_deleting_the_last_activity_also_removes_its_document(api):
    client, db, _, course, document = api
    activity = add_activity(api)

    response = client.delete(f"/api/activities/{activity.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    assert db.get(Document, document.id) is None
    assert db.get(Course, course.id) is not None
    assert client.delete(f"/api/activities/{activity.id}").status_code == 404


def test_document_remains_until_its_last_activity_is_deleted(api):
    client, db, owner, course, document = api
    first = add_activity(api)
    second = Activity(id=uuid4(), user_id=owner.id, course_id=course.id, document_id=document.id, title="Otra tarea")
    db.add(second)
    db.commit()

    assert client.delete(f"/api/activities/{first.id}").status_code == 204
    assert db.get(Document, document.id) is not None
    assert client.delete(f"/api/activities/{second.id}").status_code == 204
    assert db.get(Document, document.id) is None


def test_done_tasks_can_be_returned_to_pending(api):
    client, db, _, _, _ = api
    activity = add_activity(api)

    assert client.patch(f"/api/activities/{activity.id}/complete").json()["status"] == "completed"
    db.refresh(activity)
    assert activity.completed_at is not None
    response = client.patch(f"/api/activities/{activity.id}/reopen")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    db.refresh(activity)
    assert activity.completed_at is None


@pytest.mark.parametrize("method,suffix", [("PATCH", ""), ("DELETE", ""), ("PATCH", "/complete"), ("PATCH", "/reopen")])
def test_mutations_cannot_change_another_users_activity(api, method, suffix):
    client, db, _, _, _ = api
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    course = Course(id=uuid4(), user_id=other.id, name="Ajeno")
    activity = Activity(id=uuid4(), user_id=other.id, course_id=course.id, title="Actividad ajena")
    db.add_all([other, course, activity])
    db.commit()

    response = client.request(method, f"/api/activities/{activity.id}{suffix}", json={"title": "Cambio"})

    assert response.status_code == 404
    db.refresh(activity)
    assert activity.title == "Actividad ajena"
    assert activity.status == "pending"


@pytest.mark.parametrize("fields", [
    {"title": " "}, {"title": "Nueva", "activity_type": "invalido"},
    {"title": "Nueva", "due_date": "2026-02-30"}, {"title": "Nueva", "status": "completed"},
    {"title": "Nueva", "user_id": str(uuid4())},
])
def test_invalid_edits_do_not_modify_the_activity(api, fields):
    client, db, _, _, _ = api
    activity = add_activity(api)

    response = client.patch(f"/api/activities/{activity.id}", json=fields)

    assert response.status_code == 422
    db.refresh(activity)
    assert activity.title == "Tarea original"
    assert activity.status == "pending"


@pytest.mark.parametrize("method,suffix", [("PATCH", ""), ("DELETE", ""), ("PATCH", "/reopen")])
def test_mutations_require_authentication(api, method, suffix):
    client, db, _, _, _ = api
    activity = add_activity(api)
    app.dependency_overrides.pop(current_user)

    response = client.request(method, f"/api/activities/{activity.id}{suffix}", json={"title": "Cambio"})

    assert response.status_code == 401
    db.refresh(activity)
    assert activity.title == "Tarea original"
