from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/gestor_tareas"
    jwt_secret: str
    cors_origins: str = "http://localhost:3000"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    max_pdf_mb: int = 15
    api_requests_per_minute: int = Field(default=180, ge=1)
    login_requests_per_minute: int = Field(default=10, ge=1)
    register_requests_per_minute: int = Field(default=5, ge=1)
    analysis_requests_per_minute: int = Field(default=5, ge=1)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_ssl: bool = False
    reminder_timezone: str = "America/Costa_Rica"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
