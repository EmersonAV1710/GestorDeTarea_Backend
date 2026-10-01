# Gestor de tareas académicas — API

FastAPI es la decisión de implementación para exponer la lógica Python como servicio independiente. PostgreSQL persiste cuentas, cursos, documentos y actividades. Contrato compartido: `API_CONTRACT.md`; OpenAPI estará en `/docs`.

## Requisitos y arranque (Ubuntu)

Instala Python 3.11+, pip y PostgreSQL. En Ubuntu, crea rol y base interactivos (la contraseña se solicita dentro de `psql`, no queda en el historial):

```bash
sudo -u postgres psql
```

Dentro de `psql`: `CREATE ROLE gestor LOGIN;`, luego `\password gestor`, `CREATE DATABASE gestor_tareas OWNER gestor;` y `\q`. Copia `.env.example` a `.env`, configura `DATABASE_URL` con la contraseña local y un `JWT_SECRET` aleatorio largo, y aplica la migración: `psql -h localhost -U gestor -d gestor_tareas -f sql/001_init.sql`. La aplicación **no** ejecuta migraciones automáticamente; aplica los archivos SQL numerados una sola vez y en orden.

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
