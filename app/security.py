from datetime import datetime,timedelta,timezone
from jose import jwt,JWTError
from pwdlib import PasswordHash
from .config import settings
pwd=PasswordHash.recommended()
def hash_password(value:str)->str: return pwd.hash(value)
def verify_password(value:str, hashed:str)->bool: return pwd.verify(value,hashed)
def token_for(uid:str)->str: return jwt.encode({"sub":uid,"exp":datetime.now(timezone.utc)+timedelta(hours=12)},settings.jwt_secret,algorithm="HS256")
def user_id(token:str)->str:
    try: return jwt.decode(token,settings.jwt_secret,algorithms=["HS256"])["sub"]
    except (JWTError,KeyError): raise ValueError("Sesión inválida o vencida")
