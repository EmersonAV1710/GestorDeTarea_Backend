from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Activity, Course, Document, User
from test_activity_types import api


def confirm(client, document, proposals):
    return client.post("/api/activities/confirm", json={"document_id": str(document.id), "activities": proposals})


def upload(client, course, filename="programa.txt", contents=b"Proyecto final"):
    return client.post("/api/documents/analyze", data={"course_id": str(course.id)}, files={"file": (filename, contents, "text/plain")})


@pytest.fixture
def extractor(monkeypatch):
    calls = []
    def extract(*args):
        calls.append(args)
        return []
    monkeypatch.setattr("app.main.extract_activities", extract)
    return calls


def test_same_pending_file_resumes_in_new_course_after_explicit_move(api, extractor):
    client, db, owner, course, _ = api
    first = upload(client, course)
    assert first.status_code == 200
    document = next(doc for doc in db.scalars(select(Document)) if str(doc.id) == first.json()["document_id"])
    document.draft_proposals = [{"title": "Entrega", "description": "", "due_date": None, "review_required": True}]
    db.commit()
    another = Course(user_id=owner.id, name="Otro curso")
    db.add(another)
    db.commit()
    blocked = upload(client, another, filename="renombrado.txt")
    assert blocked.status_code == 409
    moved = client.patch(f"/api/documents/{document.id}", json={"course_id": str(another.id)})
    assert moved.status_code == 200
    response = upload(client, another, filename="renombrado.txt")
    assert response.status_code == 200
    assert response.json()["document_id"] == first.json()["document_id"]
    assert response.json()["course_id"] == str(another.id)
    assert len(extractor) == 1
    assert db.scalar(select(func.count()).select_from(Document)) == 2


def test_same_pending_file_with_no_proposals_is_analyzed_again(api, extractor):
    client, db, _, course, _ = api
    first = upload(client, course)
    second = upload(client, course)
    assert first.status_code == second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]
    assert len(extractor) == 2
    assert db.scalar(select(func.count()).select_from(Document)) == 2


def test_new_files_with_same_name_and_different_content_are_allowed(api, extractor):
    client, _, _, course, _ = api
    assert upload(client, course).status_code == 200
    assert upload(client, course, contents=b"Contenido actualizado").status_code == 200
    assert len(extractor) == 2


def test_legacy_pending_upload_recovers_the_analysis_without_another_document(api, extractor):
    client, db, _, course, document = api
    response = upload(client, course, filename=document.filename.upper())
    assert response.status_code == 200
    assert response.json()["document_id"] == str(document.id)
    assert len(extractor) == 1
    assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_same_content_can_be_uploaded_by_a_different_user(api, extractor):
    client, db, owner, course, _ = api
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    db.add(other)
    db.flush()
    db.add(Document(user_id=other.id, course_id=course.id, filename="programa.txt", content_hash=sha256(b"Proyecto final").hexdigest()))
    db.commit()
    assert upload(client, course).status_code == 200


def test_database_rejects_duplicate_content_hash_for_same_user(api):
    _, db, owner, course, document = api
    document.content_hash = sha256(b"sample").hexdigest()
    db.commit()
    db.add(Document(user_id=owner.id, course_id=course.id, filename="otra.txt", content_hash=document.content_hash))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_upload_rechecks_duplicates_after_analysis(api, extractor, monkeypatch):
    client, db, owner, course, _ = api
    def simultaneous_upload(*args):
        db.add(Document(user_id=owner.id, course_id=course.id, filename="otra.txt", content_hash=sha256(b"Proyecto final").hexdigest()))
        db.commit()
        return []
    monkeypatch.setattr("app.main.extract_activities", simultaneous_upload)
    assert upload(client, course).status_code == 200
    assert db.scalar(select(func.count()).select_from(Document)) == 2


@pytest.mark.parametrize("due_date", [None, "2026-11-20"])
def test_duplicate_proposals_reject_entire_batch_without_writes(api, due_date):
    client, db, _, _, document = api
    response = confirm(client, document, [{"title": "Entrega final", "due_date": due_date},
        {"title": "  ENTREGA   FINAL  ", "due_date": due_date, "activity_type": "proyecto"}])
    assert response.status_code == 409
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    assert document.is_confirmed is False


def test_saved_activity_cannot_be_duplicated_from_another_document_even_if_completed(api):
    client, db, owner, course, document = api
    db.add(Activity(user_id=owner.id, course_id=course.id, title="Exposición", due_date=date(2026, 11, 20), status="completed"))
    db.commit()
    response = confirm(client, document, [{"title": "Nueva"}, {"title": "EXPOSICIO\u0301N", "due_date": "2026-11-20"}])
    assert response.status_code == 409
    assert db.scalar(select(func.count()).select_from(Activity)) == 1


def test_same_title_on_different_dates_or_courses_is_allowed(api):
    client, db, owner, course, document = api
    other = Course(id=uuid4(), user_id=owner.id, name="Otro curso")
    db.add(other)
    db.add(Activity(user_id=owner.id, course_id=other.id, title="Entrega", due_date=date(2026, 11, 20)))
    db.commit()
    response = confirm(client, document, [{"title": "Entrega", "due_date": "2026-11-20"}, {"title": "Entrega", "due_date": "2026-11-21"}])
    assert response.status_code == 200
    assert db.scalar(select(func.count()).select_from(Activity)) == 3


def test_edit_cannot_duplicate_another_activity_and_can_keep_its_own_title(api):
    client, db, owner, course, _ = api
    first = Activity(user_id=owner.id, course_id=course.id, title="Primera")
    second = Activity(user_id=owner.id, course_id=course.id, title="Segunda")
    db.add_all([first, second])
    db.commit()
    assert client.patch(f"/api/activities/{second.id}", json={"title": " PRIMERA "}).status_code == 409
    db.refresh(second)
    assert second.title == "Segunda"
    assert client.patch(f"/api/activities/{first.id}", json={"title": " Primera "}).status_code == 200


def test_reconfirm_after_deleting_last_task_requires_a_new_upload(api):
    client, db, _, _, document = api
    proposals = [{"title": "Entrega"}]
    response = confirm(client, document, proposals)
    assert response.status_code == 200
    assert client.delete(f"/api/activities/{response.json()[0]['id']}").status_code == 204
    assert confirm(client, document, proposals).status_code == 404
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    assert db.get(Document, document.id) is None


def test_same_file_can_be_uploaded_after_all_its_activities_are_deleted(api, extractor):
    client, db, _, course, _ = api
    first = upload(client, course, contents=b"Proyecto final")
    assert first.status_code == 200
    document_id = first.json()["document_id"]
    saved = client.post("/api/activities/confirm", json={"document_id": document_id,
        "activities": [{"title": "Entrega final"}]})
    assert saved.status_code == 200
    assert client.delete(f"/api/activities/{saved.json()[0]['id']}").status_code == 204
    assert db.get(Document, UUID(document_id)) is None

    second = upload(client, course, contents=b"Proyecto final")

    assert second.status_code == 200
    assert second.json()["document_id"] != document_id
    assert len(extractor) == 2


def test_confirmed_uploads_remain_blocked(api, extractor):
    client, db, owner, course, document = api
    document.content_hash = sha256(b"Proyecto final").hexdigest()
    document.is_confirmed = True
    db.add(Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Entrega"))
    db.commit()
    assert upload(client, course, filename="renombrado.txt").status_code == 409
    assert extractor == []


def test_legacy_confirmed_document_without_activities_can_be_uploaded_again(api, extractor):
    client, db, _, course, document = api
    document.content_hash = sha256(b"Proyecto final").hexdigest()
    document.is_confirmed = True
    db.commit()

    response = upload(client, course, filename="renombrado.txt")

    assert response.status_code == 200
    assert response.json()["document_id"] == str(document.id)
    assert document.is_confirmed is False
    assert document.filename == "renombrado.txt"
    assert len(extractor) == 1


def test_pending_documents_preserve_proposals_and_are_private(api):
    client, db, owner, course, document = api
    proposals = [{"title": "Entrega", "description": "", "due_date": None, "review_required": True}]
    document.draft_proposals = proposals
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    db.add(other)
    db.flush()
    db.add(Document(user_id=other.id, course_id=course.id, filename="ajeno.txt", draft_proposals=proposals))
    db.commit()
    pending = client.get("/api/documents/pending").json()
    assert len(pending) == 1
    assert pending[0]["proposals"] == proposals
    assert pending[0]["document_id"] == str(document.id)
    assert confirm(client, document, proposals).status_code == 200
    assert client.get("/api/documents/pending").json() == []
    db.refresh(document)
    assert document.draft_proposals is None


def test_saved_documents_list_only_owned_documents_with_activities(api):
    client, db, owner, course, document = api
    document.is_confirmed = True
    db.add_all([
        Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Primera"),
        Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Segunda"),
    ])
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    other_document = Document(user_id=other.id, course_id=course.id, filename="ajeno.txt", is_confirmed=True)
    db.add_all([other, other_document])
    db.flush()
    db.add(Activity(user_id=other.id, course_id=course.id, document_id=other_document.id, title="Ajena"))
    db.commit()

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == [{"document_id": str(document.id), "course_id": str(course.id),
                                "filename": document.filename, "activity_count": 2}]


def test_pending_review_can_be_deleted_without_affecting_another_user(api):
    client, db, owner, course, document = api
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    other_document = Document(user_id=other.id, course_id=course.id, filename="ajeno.txt")
    db.add_all([other, other_document])
    db.commit()
    assert client.delete(f"/api/documents/{other_document.id}").status_code == 404
    assert client.delete(f"/api/documents/{document.id}").status_code == 204
    assert db.get(Document, document.id) is None
    assert db.get(Document, other_document.id) is not None
    assert client.get("/api/documents/pending").json() == []


def test_saved_document_cannot_be_deleted_as_a_pending_review(api):
    client, db, owner, course, document = api
    document.is_confirmed = True
    db.commit()
    assert client.delete(f"/api/documents/{document.id}").status_code == 409
    document.is_confirmed = False
    db.add(Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Entrega"))
    db.commit()
    assert client.delete(f"/api/documents/{document.id}").status_code == 409


def test_saved_document_deletion_removes_its_tasks_only(api):
    client, db, owner, course, document = api
    document.is_confirmed = True
    linked = [Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Primera"),
              Activity(user_id=owner.id, course_id=course.id, document_id=document.id, title="Segunda")]
    manual = Activity(user_id=owner.id, course_id=course.id, title="Manual")
    other_document = Document(user_id=owner.id, course_id=course.id, filename="otro.txt", is_confirmed=True)
    db.add_all([*linked, manual, other_document])
    db.flush()
    other_task = Activity(user_id=owner.id, course_id=course.id, document_id=other_document.id, title="Otra")
    db.add(other_task)
    db.commit()
    linked_ids = [activity.id for activity in linked]

    assert client.delete(f"/api/documents/{document.id}/saved").status_code == 204
    assert db.get(Document, document.id) is None
    assert all(db.get(Activity, activity_id) is None for activity_id in linked_ids)
    assert db.get(Activity, manual.id) is not None
    assert db.get(Activity, other_task.id) is not None
    assert db.get(Document, other_document.id) is not None
    assert client.get("/api/documents").json()[0]["document_id"] == str(other_document.id)


def test_saved_document_deletion_rejects_pending_and_other_users(api):
    client, db, owner, course, document = api
    assert client.delete(f"/api/documents/{document.id}/saved").status_code == 409
    other = User(id=uuid4(), username="other", email="other@example.invalid", password_hash="unused")
    other_document = Document(user_id=other.id, course_id=course.id, filename="ajeno.txt", is_confirmed=True)
    db.add_all([other, other_document])
    db.commit()
    assert client.delete(f"/api/documents/{other_document.id}/saved").status_code == 404
    assert db.get(Document, document.id) is not None
    assert db.get(Document, other_document.id) is not None
