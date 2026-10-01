from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/gestor_tareas"
    jwt_secret: str
    cors_origins: str = "http://localhost:3000"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    max_pdf_mb: int = 15
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
