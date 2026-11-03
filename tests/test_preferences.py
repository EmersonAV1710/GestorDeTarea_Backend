from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import token_for


def test_preferences_persist_validate_and_isolate_accounts():
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        users = [User(username=f"prefs_{suffix}_{i}", email=f"prefs-{suffix}-{i}@example.invalid", password_hash="unused") for i in range(2)]
        db.add_all(users)
        db.commit()
        ids = [user.id for user in users]
    client = TestClient(app)
    headers = [{"Authorization": f"Bearer {token_for(str(uid))}"} for uid in ids]
    url = "/api/profile/preferences"
    try:
        assert client.get(url).status_code == 401
        assert client.patch(url, json={"accent": "blue"}).status_code == 401
        assert client.get(url, headers=headers[0]).json() is None
        response = client.patch(url, headers=headers[0], json={"theme": "dark", "accent": "coral", "background": "galaxy", "language": "en", "sounds": "off"})
        assert response.status_code == 200, response.text
        assert client.get(url, headers=headers[1]).json() is None
        assert client.patch(url, headers=headers[1], json={"accent": "green"}).status_code == 200
        assert client.patch(url, headers=headers[0], json={"accent": "violet"}).status_code == 200
        expected = {"theme": "dark", "accent": "violet", "background": "galaxy", "language": "en", "sounds": "off"}
        # Another HTTP client and session token recover the database values.
        restored = TestClient(app).get(url, headers={"Authorization": f"Bearer {token_for(str(ids[0]))}"})
        assert restored.json() == expected
        assert client.get(url, headers=headers[1]).json() == {"accent": "green"}
        for invalid in [{"accent": "invalid"}, {"theme": None}, {"language": "xx"}, {"background": "invalid"}, {"sounds": "invalid"}, {"user_id": str(ids[1])}]:
            assert client.patch(url, headers=headers[0], json=invalid).status_code == 422
        assert client.get(url, headers=headers[0]).json() == expected
        for background in ["porcelain", "sky", "pistachio", "vanilla", "petals", "lilac"]:
            response = client.patch(url, headers=headers[0], json={"background": background, "theme": "light"})
            assert response.status_code == 200, response.text
            restored = client.get(url, headers=headers[0]).json()
            assert restored["background"] == background
            assert restored["theme"] == "light"
            assert restored["accent"] == "violet"
        for dark_style in ["black", "gray"]:
            response = client.patch(url, headers=headers[0], json={"dark_style": dark_style, "theme": "dark"})
            assert response.status_code == 200, response.text
            assert client.get(url, headers=headers[0]).json()["dark_style"] == dark_style
        assert client.patch(url, headers=headers[0], json={"dark_style": "invalid"}).status_code == 422
    finally:
        with SessionLocal() as db:
            for uid in ids:
                user = db.get(User, uid)
                if user:
                    db.delete(user)
            db.commit()
