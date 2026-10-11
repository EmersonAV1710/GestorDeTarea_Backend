"""No database, API key, or paid calls are needed for these tests."""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError
from pydantic import ValidationError

from app.ai import AnalysisError, MAX_TEXT_CHARS, extract_activities, parse_proposals
from app.schemas import ConfirmIn, Proposal

TEXT = "Proyecto final: entregar el informe el 20 de noviembre de 2026."
ACTIVITY = {"title": " Proyecto final ", "description": "Entregar el informe",
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


@pytest.mark.parametrize("change", [
    {"title": "  "}, {"title": "x" * 241}, {"title": 123},
    {"description": None}, {"description": "x" * 5001},
    {"due_date": "2026-02-30"}, {"due_date": "20/11/2026"},
    {"due_date": 123}, {"due_date": "2026-11-20T00:00:00"},
    {"review_required": "false"}, {"source_excerpt": "Invented evidence"},
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
    assert extract_activities(TEXT, "fake-key", "gpt-4o-mini")[0]["title"] == "Proyecto final"
    assert factory.call_args.kwargs["max_retries"] == 0
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["messages"][1]["content"] == TEXT


@pytest.mark.parametrize("finish,refusal,content", [
    ("length", None, payload()), ("content_filter", None, payload()),
    ("stop", "Cannot extract", payload()), ("stop", None, ""),
    ("stop", None, "invalid JSON"),
])
def test_incomplete_refused_and_malformed_provider_responses(monkeypatch, finish, refusal, content):
    provider(monkeypatch, content, finish, refusal)
    with pytest.raises(AnalysisError) as error:
        extract_activities(TEXT, "fake-key", "gpt-4o-mini")
    assert error.value.status_code == 502


def test_no_choices_is_an_error(monkeypatch):
    _, client = provider(monkeypatch)
    client.chat.completions.create.return_value = SimpleNamespace(choices=[])
    with pytest.raises(AnalysisError):
        extract_activities(TEXT, "fake-key", "gpt-4o-mini")


@pytest.mark.parametrize("exception,status", [
    (APITimeoutError(request=httpx.Request("POST", "https://example.invalid")), 504),
    (APIConnectionError(request=httpx.Request("POST", "https://example.invalid")), 502),
])
def test_provider_failures_have_safe_errors(monkeypatch, exception, status):
    _, client = provider(monkeypatch)
    client.chat.completions.create.side_effect = exception
    with pytest.raises(AnalysisError) as error:
        extract_activities(TEXT, "fake-key", "gpt-4o-mini")
    assert error.value.status_code == status


def test_missing_key_and_oversized_text_never_call_provider(monkeypatch):
    factory, _ = provider(monkeypatch)
    for text, key, status in [(TEXT, "", 503), ("x" * (MAX_TEXT_CHARS + 1), "fake-key", 422)]:
        with pytest.raises(AnalysisError) as error:
            extract_activities(text, key, "gpt-4o-mini")
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
