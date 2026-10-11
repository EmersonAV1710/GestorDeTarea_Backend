"""Exercise HTTP validation with an isolated database double and mocked AI."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

TEXT = "Entrega del proyecto: 20 de noviembre de 2026."


@pytest.fixture
def api(monkeypatch):
    # Import only after configuring a disposable signing secret. No DB connection.
    monkeypatch.setenv("JWT_SECRET", "isolated-test-secret-not-for-production")
    from app.main import app, current_user, get_db
    from app.config import settings
    from app.models import User

    db = MagicMock()
    course_id = uuid4()
    db.scalar.return_value = SimpleNamespace(id=course_id)
    db.add.side_effect = lambda document: setattr(document, "id", uuid4())
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr("pypdf.PdfReader", lambda _: SimpleNamespace(pages=[
        SimpleNamespace(extract_text=lambda: TEXT)]))
    factory = MagicMock()
    provider = factory.return_value.__enter__.return_value
    provider.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(finish_reason="stop", message=SimpleNamespace(refusal=None,
            content=json.dumps({"activities": [{"title": "Proyecto", "description": "",
                "due_date": "2026-11-20", "review_required": False,
                "source_excerpt": TEXT}]})))])
    monkeypatch.setattr("app.ai.OpenAI", factory)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: User(id=uuid4())
    try:
        with TestClient(app) as client:
            yield client, db, provider, course_id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def upload(api):
    client, _, _, course_id = api
    return client.post("/api/documents/analyze", data={"course_id": str(course_id)},
                       files={"file": ("synthetic.pdf", b"synthetic PDF reader fixture", "application/pdf")})


def test_success_returns_evidence_and_only_saves_document_metadata(api):
    _, db, _, _ = api
    response = upload(api)
    assert response.status_code == 200
    assert response.json()["proposals"][0]["source_excerpt"] == TEXT
    assert response.json()["document_id"]
    db.add.assert_called_once()
    assert db.add.call_args.args[0].__tablename__ == "documents"
    db.commit.assert_called_once()


def test_invalid_ai_response_is_502_without_database_writes(api):
    _, db, provider, _ = api
    provider.chat.completions.create.return_value.choices[0].message.content = '{"activities": [{}]}'
    response = upload(api)
    assert response.status_code == 502
    assert isinstance(response.json()["detail"], str)
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_empty_extraction_is_a_successful_empty_result(api):
    _, _, provider, _ = api
    provider.chat.completions.create.return_value.choices[0].message.content = '{"activities": []}'
    assert upload(api).json()["proposals"] == []


@pytest.mark.parametrize("activities", [[], [{"title": " "}],
    [{"title": "Entrega", "description": None}],
    [{"title": "Entrega", "due_date": "2026-02-30"}]])
def test_invalid_confirmation_is_422_without_database_writes(api, activities):
    client, db, _, _ = api
    response = client.post("/api/activities/confirm", json={
        "document_id": str(uuid4()), "activities": activities})
    assert response.status_code == 422
    db.add.assert_not_called()
    db.commit.assert_not_called()
