# Gestor de tareas académicas — API

FastAPI es la decisión de implementación para exponer la lógica Python como servicio independiente. PostgreSQL persiste cuentas, cursos, documentos y actividades. Contrato compartido: `API_CONTRACT.md`; OpenAPI estará en `/docs`.

## Requisitos y arranque (Ubuntu)

Instala Python 3.11+, pip y PostgreSQL. Crea una base/usuario propios, copia `.env.example` a `.env`, define `DATABASE_URL` y `JWT_SECRET`, y ejecuta `psql "$DATABASE_URL" -f sql/001_init.sql`. La aplicación **no** ejecuta migraciones automáticamente.

```bash
cd ~/proyectos/GestorDeTarea_Backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edita secretos localmente; nunca los subas
uvicorn app.main:app --reload
```

No hay clave universal ni alta pública. Para preparar una cuenta local, usa `python -m app.create_user correo@ejemplo.com`; se solicita la contraseña de forma interactiva. PDFs: solo PDF con texto, máximo 15 MB por defecto; PDFs escaneados requieren OCR, fuera de esta versión. El análisis real usa OpenAI cuando se configura `OPENAI_API_KEY`; sin clave devuelve error explicativo y no crea extracción de prueba.

## Privacidad

Todas las consultas y mutaciones están acotadas al usuario autenticado. No se guardan archivos PDF; solo metadatos y propuestas confirmadas. No incluyas documentos reales, `.env`, claves ni contraseñas en Git.
