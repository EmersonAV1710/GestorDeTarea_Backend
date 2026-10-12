"""Exercise HTTP validation with an isolated database double and mocked AI."""
import json
import io
import zipfile
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
    from app.request_limits import enforce_request_limits
    from app.config import settings
    from app.models import User

    db = MagicMock()
    course_id = uuid4()
    db.scalar.return_value = SimpleNamespace(id=course_id, is_active=True)
    db.scalars.return_value = []
    db.add.side_effect = lambda document: setattr(document, "id", uuid4())
    monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
    monkeypatch.setattr("app.document_text.PdfReader", lambda _: SimpleNamespace(pages=[
        SimpleNamespace(extract_text=lambda: TEXT)]))
    factory = MagicMock()
    provider = factory.return_value.__enter__.return_value
    provider.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(finish_reason="stop", message=SimpleNamespace(refusal=None,
            content=json.dumps({"activities": [{"activity_type": "proyecto", "title": "Proyecto", "description": "",
                "due_date": "2026-11-20", "review_required": False,
                "source_excerpt": TEXT}]})))])
    monkeypatch.setattr("app.ai.OpenAI", factory)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[enforce_request_limits] = lambda: None
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


def docx_bytes(text: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def test_success_returns_evidence_and_only_saves_document_metadata(api):
    _, db, _, _ = api
    response = upload(api)
    assert response.status_code == 200
    assert response.json()["proposals"][0]["source_excerpt"] == TEXT
    assert response.json()["document_id"]
    db.add.assert_called_once()
    assert db.add.call_args.args[0].__tablename__ == "documents"
    db.commit.assert_called_once()


def test_one_bad_excerpt_returns_a_reviewable_proposal_instead_of_losing_the_analysis(api):
    _, db, provider, _ = api
    provider.chat.completions.create.return_value.choices[0].message.content = json.dumps({"activities": [
        {"activity_type": "proyecto", "title": "Proyecto", "description": "", "due_date": "2026-11-20",
         "review_required": False, "source_excerpt": TEXT},
        {"activity_type": "tarea", "title": "Tarea por comprobar", "description": "", "due_date": "2026-11-21",
         "review_required": False, "source_excerpt": "Cita que no aparece"},
    ]})

    response = upload(api)

    assert response.status_code == 200
    assert len(response.json()["proposals"]) == 2
    doubtful = response.json()["proposals"][1]
    assert doubtful["source_excerpt"] == ""
    assert doubtful["due_date"] is None
    assert doubtful["review_required"] is True
    db.commit.assert_called_once()


@pytest.mark.parametrize("filename,contents,mime", [
    ("programa.docx", docx_bytes(TEXT), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("programa.txt", TEXT.encode(), "text/plain"),
], ids=["docx", "txt"])
def test_word_and_txt_uploads_return_proposals(api, filename, contents, mime):
    client, db, _, course_id = api
    response = client.post("/api/documents/analyze", data={"course_id": str(course_id)},
                           files={"file": (filename, contents, mime)})
    assert response.status_code == 200
    assert response.json()["proposals"][0]["source_excerpt"] == TEXT
    assert db.add.call_args.args[0].filename == filename


@pytest.mark.parametrize("filename,contents,mime,expected_status", [
    ("invalido.docx", b"no es un docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 422),
    ("vacio.txt", b" \n", "text/plain", 422),
    ("binario.txt", b"\x00\x01", "text/plain", 422),
    ("antiguo.doc", b"archivo", "application/msword", 415),
])
def test_invalid_documents_do_not_create_metadata(api, filename, contents, mime, expected_status):
    client, db, _, course_id = api
    response = client.post("/api/documents/analyze", data={"course_id": str(course_id)},
                           files={"file": (filename, contents, mime)})
    assert response.status_code == expected_status
    db.add.assert_not_called()


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


@pytest.mark.parametrize("filename,raw,mime", [
    ("programa.txt", TEXT.encode("utf-16"), "text/plain"),
    ("programa.txt", TEXT.encode("utf-32"), "text/plain"),
    ("documento", TEXT.encode(), "text/plain; charset=utf-8"),
    ("documento", docx_bytes(TEXT), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
])
def test_additional_encodings_and_missing_extensions_work_through_the_analysis_endpoint(api, filename, raw, mime):
    client, db, provider, course_id = api
    response = client.post("/api/documents/analyze", data={"course_id": str(course_id)}, files={"file": (filename, raw, mime)})
    assert response.status_code == 200
    assert response.json()["proposals"][0]["source_excerpt"] == TEXT
    provider.chat.completions.create.assert_called_once()
    db.commit.assert_called_once()
