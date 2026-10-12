from datetime import date
from uuid import UUID
from typing import Literal
import re
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

def normalize_email(value:str)->str:
    email=value.strip().lower()
    if len(email)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Ingresa un correo electrónico válido")
    return email
def normalize_username(value:str)->str:
    username=value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,29}",username):
        raise ValueError("El usuario debe tener entre 3 y 30 caracteres y usar letras, números, punto, guion o guion bajo")
    return username
def validate_password(value:str)->str:
    if len(value)<8: raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if not any(unicodedata.category(character) == "Lu" for character in value):
        raise ValueError("La contraseña debe tener al menos una mayúscula")
    if not any(character.isdecimal() for character in value):
        raise ValueError("La contraseña debe tener al menos un número")
    if value.strip()!=value: raise ValueError("La contraseña no puede iniciar ni terminar con espacios")
    return value
class Login(BaseModel):
    username:str
    password:str=Field(min_length=1)
    @field_validator("username")
    @classmethod
    def username_valid(cls,value): return normalize_username(value)
class RegisterIn(BaseModel):
    email:str
    username:str
    password:str
    password_confirmation:str
    @field_validator("email")
    @classmethod
    def email_valid(cls,value): return normalize_email(value)
    @field_validator("username")
    @classmethod
    def username_valid(cls,value): return normalize_username(value)
    @field_validator("password")
    @classmethod
    def password_valid(cls,value): return validate_password(value)
    @field_validator("password_confirmation")
    @classmethod
    def confirmation_length(cls,value):
        if len(value)<8: raise ValueError("La confirmación debe tener al menos 8 caracteres")
        return value
class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=80)
    term: str | None = Field(default=None, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        name = value.strip()
        if not name:
            raise ValueError("El nombre del curso no puede quedar vacío")
        return name

    @field_validator("code", "term")
    @classmethod
    def clean_optional(cls, value):
        if value is None:
            return None
        return value.strip() or None

class CourseOut(CourseIn):
    id: UUID
    is_active: bool
ActivityType = Literal["tarea", "proyecto", "examen", "exposicion", "laboratorio", "lectura", "otro"]

class Proposal(BaseModel):
    activity_type: ActivityType = "otro"
    title: str = Field(min_length=1, max_length=240, strict=True)
    description: str = Field(default="", max_length=5000, strict=True)
    due_date: date | None = None
    review_required: bool = Field(default=False, strict=True)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("due_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        if value is not None and not (
            type(value) is date or
            isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)
        ):
            raise ValueError("La fecha debe usar YYYY-MM-DD o quedar sin fecha")
        return value

    @model_validator(mode="after")
    def missing_date_needs_review(self):
        if self.due_date is None:
            self.review_required = True
        return self

class ActivityUpdate(Proposal):
    model_config = ConfigDict(extra="forbid")

class ActivityOut(Proposal): id:UUID; course_id:UUID; document_id:UUID|None; status:str
class ConfirmProposal(Proposal):
    status: Literal["pending", "completed"] = "pending"

class ManualActivityIn(ConfirmProposal):
    model_config = ConfigDict(extra="forbid")
    course_id: UUID

class ConfirmIn(BaseModel):
    document_id: UUID
    activities: list[ConfirmProposal] = Field(min_length=1, max_length=200)
