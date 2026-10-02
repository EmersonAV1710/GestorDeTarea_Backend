from datetime import date
from uuid import UUID
import re
from pydantic import BaseModel, Field, field_validator

COMMON_PASSWORDS={"passwordpassword", "contrasenasegura", "123456789012345", "qwertyuiopasdfg", "administrador123"}
def normalize_email(value:str)->str:
    email=value.strip().lower()
    if len(email)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Ingresa un correo electrónico válido")
    return email
def validate_password(value:str)->str:
    if len(value)<8: raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if len(value)>128: raise ValueError("La contraseña no puede superar 128 caracteres")
    if value.strip()!=value: raise ValueError("La contraseña no puede iniciar ni terminar con espacios")
    if value.casefold() in COMMON_PASSWORDS: raise ValueError("Elige una contraseña menos común")
    return value
class Login(BaseModel):
    email:str
    password:str=Field(min_length=1,max_length=128)
    @field_validator("email")
    @classmethod
    def email_valid(cls,value): return normalize_email(value)
class RegisterIn(BaseModel):
    email:str
    password:str
    password_confirmation:str
    @field_validator("email")
    @classmethod
    def email_valid(cls,value): return normalize_email(value)
    @field_validator("password")
    @classmethod
    def password_valid(cls,value): return validate_password(value)
    @field_validator("password_confirmation")
    @classmethod
    def confirmation_length(cls,value):
        if not 8<=len(value)<=128: raise ValueError("La confirmación debe tener entre 8 y 128 caracteres")
        return value
class CourseIn(BaseModel): name:str=Field(min_length=1,max_length=160); code:str|None=None; term:str|None=None
class CourseOut(CourseIn): id:UUID
class Proposal(BaseModel): title:str=Field(min_length=1,max_length=240); description:str=""; due_date:date|None=None; review_required:bool=False
class ActivityOut(Proposal): id:UUID; course_id:UUID; document_id:UUID|None; status:str
class ConfirmIn(BaseModel): document_id:UUID; activities:list[Proposal]
