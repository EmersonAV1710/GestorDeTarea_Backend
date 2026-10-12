from datetime import datetime,timedelta,timezone
from jose import jwt,JWTError
from uuid import uuid4
from hashlib import sha256
from pwdlib import PasswordHash
from .config import settings
pwd=PasswordHash.recommended()
def hash_password(value:str)->str: return pwd.hash(value)
def verify_password(value:str, hashed:str)->bool: return pwd.verify(value,hashed)
def token_for(uid: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": uid, "jti": uuid4().hex, "iat": now, "exp": now + timedelta(hours=12)}, settings.jwt_secret, algorithm="HS256")


def token_claims(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require_exp": True, "require_sub": True})
    except (JWTError, KeyError) as exc:
        raise ValueError("Sesión inválida o vencida") from exc


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def user_id(token: str) -> str:
    return token_claims(token)["sub"]
