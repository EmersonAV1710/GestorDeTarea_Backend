# Gestor de tareas académicas — API

FastAPI es la decisión de implementación para exponer la lógica Python como servicio independiente. PostgreSQL persiste cuentas, cursos, documentos y actividades. Durante el desarrollo se usa PostgreSQL local en Ubuntu; cuando el equipo tenga cuenta, la misma base podrá alojarse en Supabase cambiando únicamente `DATABASE_URL`. FastAPI conserva autenticación, autorización y lógica de negocio: no se usa Supabase Auth, SDK ni API de base de datos. El SQL de `sql/` usa PostgreSQL estándar para que las migraciones puedan aplicarse también al PostgreSQL de Supabase. Contrato compartido: `API_CONTRACT.md`; OpenAPI estará en `/docs`.

## Requisitos y arranque (Ubuntu)

Instala Python 3.11+, pip y PostgreSQL. En Ubuntu, crea rol y base interactivos (la contraseña se solicita dentro de `psql`, no queda en el historial):

```bash
sudo -u postgres psql
```

Dentro de `psql`: `CREATE ROLE gestor LOGIN;`, luego `\password gestor`, `CREATE DATABASE gestor_tareas OWNER gestor;` y `\q`. Copia `.env.example` a `.env`, configura `DATABASE_URL` con la contraseña local y un `JWT_SECRET` aleatorio largo, y aplica la migración: `psql -h localhost -U gestor -d gestor_tareas -f sql/001_init.sql`. La aplicación **no** ejecuta migraciones automáticamente; aplica los archivos SQL numerados una sola vez y en orden. Para un PostgreSQL nuevo, establece allí `DATABASE_URL` y aplica los mismos archivos con `psql "$DATABASE_URL" -f sql/001_init.sql`.

```bash
cd ~/proyectos/GestorDeTarea_Backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt  # incluye pytest para las comprobaciones locales
cp .env.example .env  # edita secretos localmente; nunca los subas
uvicorn app.main:app --reload
```

No hay clave universal ni alta pública. Para preparar una cuenta local, usa `python -m app.create_user correo@ejemplo.com`; se solicita la contraseña de forma interactiva. PDFs: solo PDF con texto, máximo 15 MB por defecto; PDFs escaneados requieren OCR, fuera de esta versión. El análisis real usa OpenAI cuando se configura `OPENAI_API_KEY`; sin clave devuelve error explicativo y no crea extracción de prueba.

## Privacidad

Todas las consultas y mutaciones están acotadas al usuario autenticado. No se guardan archivos PDF; solo metadatos y propuestas confirmadas. No incluyas documentos reales, `.env`, claves ni contraseñas en Git.

## Traslado opcional de datos de prueba

El uso normal no requiere exportar ni importar datos: cuando migren a Supabase, creen la base vacía y apliquen las migraciones. Si el equipo necesita conservar datos locales de desarrollo, puede exportarlos explícitamente y restaurarlos en el destino PostgreSQL; no versionen el archivo de respaldo y no usen documentos ni datos reales del curso.

```bash
# En backend, origen local: solicita contraseña de forma interactiva
pg_dump -h localhost -U gestor -d gestor_tareas -Fc -f /tmp/gestor_tareas.dump
# En destino, tras configurar una DATABASE_URL temporal para Supabase
pg_restore --no-owner --no-privileges -d "$DATABASE_URL" /tmp/gestor_tareas.dump
```

Este paso es opcional y separado de la migración de esquema. Mantengan `DATABASE_URL` del destino fuera de Git y no guarden el dump en el repositorio.

## Pruebas de integración

Con PostgreSQL de desarrollo activo y `.env` apuntando a una base vacía con la migración aplicada, ejecuta `pytest`. Las pruebas crean datos temporales con correo `.invalid` y los eliminan al finalizar. Comprueban login, aislamiento por usuario, filtros inclusivos, orden de próximas tareas, estado completado persistente e idempotencia de confirmación; no llaman al proveedor de IA.
