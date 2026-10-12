import pytest
from pydantic import ValidationError

from app.schemas import Login, RegisterIn
from test_activity_types import api


@pytest.mark.parametrize("password", ["Clave8ok", "Ñandú123", "A" + "x" * 150 + "1"])
def test_registration_accepts_passwords_meeting_all_rules_without_128_character_limit(password):
    body = RegisterIn(email="rules@example.invalid", username="rules", password=password, password_confirmation=password)
    assert body.password == password
    assert Login(username="rules", password=password).password == password


@pytest.mark.parametrize("password,message", [("Clave1", "8 caracteres"), ("clave123", "mayúscula"), ("ClaveLarga", "número")])
def test_registration_rejects_each_missing_password_requirement(password, message):
    with pytest.raises(ValidationError, match=message):
        RegisterIn(email="rules@example.invalid", username="rules", password=password, password_confirmation=password)


def test_long_password_can_register_and_login_through_http(api):
    client, _, _, _, _ = api
    password = "Clave" + "x" * 150 + "1"
    response = client.post("/api/auth/register", json={"email": "long@example.invalid", "username": "longuser", "password": password, "password_confirmation": password})
    assert response.status_code == 201
    assert client.post("/api/auth/login", json={"username": "longuser", "password": password}).status_code == 200


@pytest.mark.parametrize("password", ["Clave1", "clave123", "ClaveLarga"])
def test_http_registration_rejects_missing_requirements(api, password):
    client, _, _, _, _ = api
    assert client.post("/api/auth/register", json={"email": "invalid@example.invalid", "username": "invaliduser", "password": password, "password_confirmation": password}).status_code == 422
