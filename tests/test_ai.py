"""No database, API key, or paid calls are needed for these tests."""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError, OpenAI
from pydantic import ValidationError

from app.ai import AnalysisError, MAX_TEXT_CHARS, OUTPUT_SCHEMA, extract_activities, parse_proposals
from app.schemas import ConfirmIn, Proposal

TEXT = "Proyecto final: entregar el informe el 20 de noviembre de 2026."
ACTIVITY = {"activity_type": "proyecto", "title": " Proyecto final ", "description": "Entregar el informe",
            "due_date": "2026-11-20", "review_required": False,
            "source_excerpt": TEXT}


def payload(**changes):
    return json.dumps({"activities": [{**ACTIVITY, **changes}]})


def test_valid_proposals_have_calendar_dates_evidence_and_trimmed_titles():
    result = parse_proposals(payload(), TEXT)
    assert result[0]["title"] == "Proyecto final"
    assert result[0]["due_date"] == "2026-11-20"
    assert result[0]["source_excerpt"] == TEXT


def test_missing_date_is_always_flagged_and_empty_description_is_allowed():
    result = parse_proposals(payload(due_date=None, description=""), TEXT)
    assert result[0]["review_required"] is True
    assert result[0]["description"] == ""


def test_uncertain_year_keeps_date_empty_and_exposes_specific_warning():
    text = "Entrega del proyecto: 20 de noviembre."
    result = parse_proposals(payload(source_excerpt=text, due_date="2026-11-20",
                                     year_unconfirmed=True, review_required=False), text)
    assert result[0]["year_unconfirmed"] is True
    assert result[0]["due_date"] is None
    assert result[0]["review_required"] is True
    fields = OUTPUT_SCHEMA["properties"]["activities"]["items"]
    assert "year_unconfirmed" in fields["required"]


def test_uncertain_year_warning_is_separate_from_description():
    text = "Diagnóstico de la empresa: 10 de noviembre."
    description = "Preparar el diagnóstico. El año no se especifica explícitamente en el texto, por lo que la fecha debe revisarse."
    result = parse_proposals(payload(source_excerpt=text, due_date=None,
                                     year_unconfirmed=True, description=description), text)
    assert result[0]["description"] == "Preparar el diagnóstico."
    assert result[0]["year_unconfirmed"] is True


def test_short_uncertain_year_warning_is_separate_from_description():
    text = "Diagnóstico de la empresa: 10 de noviembre."
    result = parse_proposals(payload(source_excerpt=text, due_date=None,
                                     year_unconfirmed=True,
                                     description="Preparar el diagnóstico. El año no se especifica en el texto."), text)
    assert result[0]["description"] == "Preparar el diagnóstico."
    assert result[0]["year_unconfirmed"] is True


def test_alternative_week_dates_are_kept_out_of_description():
    text = "Exposición del proyecto: semana A 20 octubre, semana B 27 octubre."
    reason = "Fechas alternativas entre semana A (20 octubre) y semana B (27 octubre)."
    result = parse_proposals(payload(source_excerpt=text, due_date=None,
                                     description=f"Presentar el proyecto. {reason}"), text)
    assert result[0]["description"] == "Presentar el proyecto."
    assert result[0]["date_warning_reason"] == reason
    assert "date_warning_reason" in OUTPUT_SCHEMA["properties"]["activities"]["items"]["required"]


@pytest.mark.parametrize("change", [
    {"title": "  "}, {"title": "x" * 241}, {"title": 123},
    {"description": None}, {"description": "x" * 5001},
    {"due_date": "2026-02-30"}, {"due_date": "20/11/2026"},
    {"due_date": 123}, {"due_date": "2026-11-20T00:00:00"},
    {"review_required": "false"}, {"source_excerpt": "Invented evidence"},
    {"year_unconfirmed": "true"},
    {"source_excerpt": " "}, {"unexpected": "field"},
])
def test_invalid_proposals_are_rejected(change):
    with pytest.raises(AnalysisError) as error:
        parse_proposals(payload(**change), TEXT)
    assert error.value.status_code == 502


@pytest.mark.parametrize("content", ["not JSON", "{}", "[]", '{"activities": null}',
                                       '{"activities": [null]}', '{"activities": [{}]}'])
def test_invalid_envelopes_are_rejected(content):
    with pytest.raises(AnalysisError):
        parse_proposals(content, TEXT)


def test_empty_results_are_valid_and_exact_duplicates_are_removed():
    assert parse_proposals('{"activities": []}', TEXT) == []
    content = json.dumps({"activities": [ACTIVITY, ACTIVITY]})
    assert len(parse_proposals(content, TEXT)) == 1


def test_evidence_accepts_pdf_whitespace_variations():
    result = parse_proposals(payload(), TEXT.replace(" ", "\n"))
    assert len(result) == 1


def provider(monkeypatch, content=None, finish="stop", refusal=None):
    factory = MagicMock()
    client = factory.return_value.__enter__.return_value
    client.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(finish_reason=finish, message=SimpleNamespace(
            content=content if content is not None else payload(), refusal=refusal))])
    monkeypatch.setattr("app.ai.OpenAI", factory)
    return factory, client


def test_provider_call_uses_schema_and_does_not_retry(monkeypatch):
    factory, client = provider(monkeypatch)
    assert extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")[0]["title"] == "Proyecto final"
    assert factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert factory.call_args.kwargs["api_key"] == "fake-key"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash-lite"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["messages"][1]["content"] == TEXT


def test_syllabus_prompt_and_response_handle_deliveries_and_uncertain_dates(monkeypatch):
    syllabus = ("Programa de curso. II Ciclo 2026.\n"
                "Evaluación: Tareas (1, 2) 15%. Examen 20%.\n"
                "Sesión 1 | 21 julio, 2026 | Asignar Tarea 1.\n"
                "Sesión 2 | 28 julio, 2026 | Entrega Tarea 1.\n"
                "Sesión 4 | 11 agosto, 2026 | Entrega Tarea 2. SEMANA A.\n"
                "Sesión 5 | 18 agosto, 2026 | Entrega Tarea 2. SEMANA B.\n"
                "Sesión 12 | 6 octubre, 2026 | Examen.\n"
                "Sesión 13 | 13 octubre, 2026 | EXAMEN en línea.")
    activities = [
        {"activity_type": "tarea", "title": "Entrega Tarea 1", "description": "Entregar la Tarea 1.",
         "due_date": "2026-07-28", "review_required": False, "source_excerpt": "Entrega Tarea 1."},
        {"activity_type": "tarea", "title": "Entrega Tarea 2", "description": "La fecha depende de la semana A o B.",
         "due_date": None, "review_required": True, "source_excerpt": "Entrega Tarea 2."},
        {"activity_type": "examen", "title": "Examen", "description": "El cronograma muestra sesiones contradictorias; revisar la fecha.",
         "due_date": None, "review_required": True, "source_excerpt": "EXAMEN en línea."},
    ]
    _, client = provider(monkeypatch, json.dumps({"activities": activities}))

    result = extract_activities(syllabus, "fake-key", "gemini-3.5-flash-lite")

    assert [(item["title"], item["due_date"], item["review_required"]) for item in result] == [
        ("Entrega Tarea 1", "2026-07-28", False),
        ("Entrega Tarea 2", None, True),
        ("Examen", None, True),
    ]
    prompt, document = client.chat.completions.create.call_args.kwargs["messages"]
    assert prompt["role"] == "system"
    assert "Asignar Tarea 2" in prompt["content"]
    assert "semanas A/B" in prompt["content"]
    assert "no confiable" in prompt["content"]
    assert document == {"role": "user", "content": syllabus}


def test_one_unverified_excerpt_does_not_discard_verified_activities(monkeypatch):
    text = "Entrega Tarea 1 el 20 de noviembre de 2026.\nEntrega Tarea 2."
    activities = [
        {**ACTIVITY, "title": "Tarea 1", "source_excerpt": "Entrega Tarea 1"},
        {**ACTIVITY, "title": "Tarea 2", "source_excerpt": "Entrega inventada Tarea 2."},
    ]
    _, client = provider(monkeypatch, json.dumps({"activities": activities}))

    result = extract_activities(text, "fake-key", "gemini-3.5-flash-lite")

    assert len(result) == 2
    assert result[0]["source_excerpt"] == "Entrega Tarea 1"
    assert result[0]["due_date"] == "2026-11-20"
    assert result[1]["source_excerpt"] == ""
    assert result[1]["due_date"] is None
    assert result[1]["review_required"] is True
    client.chat.completions.create.assert_called_once()


def test_all_unverified_excerpts_still_fail(monkeypatch):
    provider(monkeypatch, payload(source_excerpt="Entrega inventada."))
    with pytest.raises(AnalysisError, match="ninguna actividad"):
        extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")


@pytest.mark.parametrize("finish,refusal,content", [
    ("length", None, payload()), ("content_filter", None, payload()),
    ("stop", "Cannot extract", payload()), ("stop", None, ""),
    ("stop", None, "invalid JSON"),
])
def test_incomplete_refused_and_malformed_provider_responses(monkeypatch, finish, refusal, content):
    provider(monkeypatch, content, finish, refusal)
    with pytest.raises(AnalysisError) as error:
        extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")
    assert error.value.status_code == 502


def test_no_choices_is_an_error(monkeypatch):
    _, client = provider(monkeypatch)
    client.chat.completions.create.return_value = SimpleNamespace(choices=[])
    with pytest.raises(AnalysisError):
        extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")


@pytest.mark.parametrize("exception,status", [
    (APITimeoutError(request=httpx.Request("POST", "https://example.invalid")), 504),
    (APIConnectionError(request=httpx.Request("POST", "https://example.invalid")), 502),
])
def test_provider_failures_have_safe_errors(monkeypatch, exception, status):
    _, client = provider(monkeypatch)
    client.chat.completions.create.side_effect = exception
    with pytest.raises(AnalysisError) as error:
        extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")
    assert error.value.status_code == status


def test_missing_key_and_oversized_text_never_call_provider(monkeypatch):
    factory, _ = provider(monkeypatch)
    for text, key, status in [(TEXT, "", 503), ("x" * (MAX_TEXT_CHARS + 1), "fake-key", 422)]:
        with pytest.raises(AnalysisError) as error:
            extract_activities(text, key, "gemini-3.5-flash-lite")
        assert error.value.status_code == status
    factory.assert_not_called()


def test_confirmation_validation_is_independent_of_ai():
    proposal = Proposal(title="  Entrega  ", description="", due_date=None)
    assert proposal.title == "Entrega" and proposal.review_required is True
    assert Proposal(title="Entrega", due_date=date(2026, 11, 20)).due_date == date(2026, 11, 20)
    with pytest.raises(ValidationError):
        Proposal(title=" ")
    with pytest.raises(ValidationError):
        ConfirmIn(document_id="00000000-0000-0000-0000-000000000001", activities=[])


@pytest.mark.parametrize("error_type,status", [
    (AuthenticationError, 503), (PermissionDeniedError, 503), (RateLimitError, 429),
])
def test_gemini_credentials_and_quota_failures_are_explained(monkeypatch, error_type, status):
    _, client = provider(monkeypatch)
    response = httpx.Response(429 if error_type is RateLimitError else 403,
                              request=httpx.Request("POST", "https://example.invalid"))
    client.chat.completions.create.side_effect = error_type("provider detail", response=response, body=None)

    with pytest.raises(AnalysisError) as error:
        extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")

    assert error.value.status_code == status
    assert "Gemini" in str(error.value)
    assert "provider detail" not in str(error.value)
    client.chat.completions.create.assert_called_once()


def test_real_client_sends_the_expected_request_to_gemini_without_network(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": "gemini-3.5-flash-lite", "choices": [{"index": 0,
                "finish_reason": "stop", "message": {"role": "assistant", "content": payload()}}],
        })

    def create_client(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr("app.ai.OpenAI", create_client)
    proposals = extract_activities(TEXT, "fake-key", "gemini-3.5-flash-lite")

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert request.headers["authorization"] == "Bearer fake-key"
    body = json.loads(request.content)
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["response_format"]["type"] == "json_schema"
    assert proposals[0]["title"] == "Proyecto final"


@pytest.mark.parametrize("activity_type", ["invalido", None, 123])
def test_extraction_rejects_invalid_delivery_types(activity_type):
    with pytest.raises(AnalysisError):
        parse_proposals(payload(activity_type=activity_type), TEXT)


def test_extraction_requires_a_delivery_type_from_gemini():
    activity = {key: value for key, value in ACTIVITY.items() if key != "activity_type"}
    with pytest.raises(AnalysisError):
        parse_proposals(json.dumps({"activities": [activity]}), TEXT)


def test_table_evidence_accepts_cell_separators_and_returns_the_original_document_text():
    text = "Actividad / contexto\nFecha indicada\nObservación\nPrueba de integración\n25-11-26\nEntregar registro de pruebas."
    content = payload(title="Prueba de integración", due_date="2026-11-25",
                      source_excerpt="Prueba de integración | 25-11-26 | Entregar registro de pruebas.")

    result = parse_proposals(content, text)

    assert result[0]["source_excerpt"] == "Prueba de integración\n25-11-26\nEntregar registro de pruebas."
    assert result[0]["source_excerpt"] in text


@pytest.mark.parametrize("excerpt", [
    "Prueba de integración | 26-11-26 | Entregar registro de pruebas.",
    "Prueba de integración | 25-11-26 | Entregar proyecto final.",
    "Prueba de integración | Entregar registro de pruebas.",
    "Entregar registro de pruebas. | 25-11-26 | Prueba de integración",
    " | | ",
])
def test_table_evidence_still_rejects_changed_dates_words_omissions_and_reordered_cells(excerpt):
    text = "Prueba de integración\n25-11-26\nEntregar registro de pruebas."
    with pytest.raises(AnalysisError):
        parse_proposals(payload(source_excerpt=excerpt), text)


@pytest.mark.parametrize("text,excerpt", [
    ('Entrega del “proyecto final” el 20 de noviembre de 2026.', 'Entrega del "proyecto final" el 20 de noviembre de 2026.'),
    ("Entrega del informe ﬁnal el 20 de noviembre de 2026.", "Entrega del informe final el 20 de noviembre de 2026."),
    ("Exposicio\u0301n del proyecto el 20 de noviembre de 2026.", "Exposición del proyecto el 20 de noviembre de 2026."),
    ("Informe de ofi\u00adcina el 20 de noviembre de 2026.", "Informe de oficina el 20 de noviembre de 2026."),
    ("Prueba de integra\u0301ción\n25-11-26\nEntregar informe ﬁnal.", "Prueba de integráción | 25-11-26 | Entregar informe final."),
])
def test_equivalent_typography_is_accepted_and_original_document_text_is_preserved(text, excerpt):
    result = parse_proposals(payload(source_excerpt=excerpt), text)
    assert result[0]["source_excerpt"] == text
    assert result[0]["source_excerpt"] in text


@pytest.mark.parametrize("excerpt", [
    'Entrega del "proyecto final" el 21 de noviembre de 2026.',
    'Entrega del "examen final" el 20 de noviembre de 2026.',
    'Entrega del "proyecto final" noviembre de 2026.',
])
def test_typography_normalization_does_not_accept_changed_words_dates_or_omissions(excerpt):
    text = 'Entrega del “proyecto ﬁnal” el 20 de noviembre de 2026.'
    with pytest.raises(AnalysisError):
        parse_proposals(payload(source_excerpt=excerpt), text)


def test_invalid_fields_are_identified_without_exposing_the_provider_payload():
    with pytest.raises(AnalysisError) as error:
        parse_proposals(payload(due_date="2026-02-30"), TEXT)
    assert "actividad 1" in str(error.value)
    assert "fecha" in str(error.value)
    assert "2026-02-30" not in str(error.value)
