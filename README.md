# Gestor de tareas académicas — API

Pruebas de extracción y validación sin PostgreSQL ni llamadas pagadas:
`python -m pytest tests/test_ai.py tests/test_analysis_api.py -q`.
Instala antes `requirements-dev.txt`. Las pruebas existentes de `test_api.py`
siguen necesitando PostgreSQL y sus migraciones. El análisis usa salidas
estructuradas; el modelo configurado debe admitir JSON Schema. Los límites y
errores están descritos en `API_CONTRACT.md`.

FastAPI es la decisión de implementación para exponer la lógica Python como servicio independiente. PostgreSQL persiste cuentas, cursos, documentos y actividades. Durante el desarrollo se usa PostgreSQL local en Ubuntu; cuando el equipo tenga cuenta, la misma base podrá alojarse en Supabase cambiando únicamente `DATABASE_URL`. FastAPI conserva autenticación, autorización y lógica de negocio: no se usa Supabase Auth, SDK ni API de base de datos. El SQL de `sql/` usa PostgreSQL estándar para que las migraciones puedan aplicarse también al PostgreSQL de Supabase. Contrato compartido: `API_CONTRACT.md`; OpenAPI estará en `/docs`.

## Requisitos y arranque (Ubuntu)

Instala Python 3.11+, pip y PostgreSQL. En Ubuntu, crea rol y base interactivos (la contraseña se solicita dentro de `psql`, no queda en el historial):

```bash
sudo -u postgres psql
```

Dentro de `psql`: `CREATE ROLE gestor LOGIN;`, luego `\password gestor`, `CREATE DATABASE gestor_tareas OWNER gestor;` y `\q`. Copia `.env.example` a `.env`, configura `DATABASE_URL` con la contraseña local y un `JWT_SECRET` aleatorio largo. La aplicación **no** ejecuta migraciones automáticamente: aplica `sql/001_init.sql` y las migraciones `002` a `008` en orden. Para `psql`, usa una URL estándar `postgresql://` o sus parámetros `host`, `user` y `dbname`; la URL `postgresql+psycopg://` del backend es exclusiva de SQLAlchemy.

```bash
cd ~/proyectos/GestorDeTarea_Backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt  # incluye pytest para las comprobaciones locales
cp .env.example .env  # edita secretos localmente; nunca los subas
uvicorn app.main:app --reload
```

## Conectar Supabase Postgres

Este proyecto conserva FastAPI como API y autenticación; Supabase aloja únicamente PostgreSQL. El frontend sigue apuntando a FastAPI mediante `NEXT_PUBLIC_API_URL`, sin clave ni URL de base de datos en el navegador.

1. Crea un proyecto vacío en Supabase. En **Connect**, copia la cadena de **Session pooler** si tu máquina o servidor usa IPv4; para un servidor con IPv6 puedes usar **Direct connection**. Usa siempre el host y usuario exactos que muestra tu proyecto.
2. En `GestorDeTarea_Backend/.env`, reemplaza `DATABASE_URL` por esa cadena, cambiando solo el prefijo `postgresql://` por `postgresql+psycopg://` y añadiendo `?sslmode=require`. Por ejemplo: `DATABASE_URL=postgresql+psycopg://postgres.REFERENCIA:CONTRASEÑA@HOST_DEL_POOLER:5432/postgres?sslmode=require`. Sustituye `[YOUR-PASSWORD]` por la contraseña de la base con los caracteres reservados codificados como URL. Conserva `JWT_SECRET` y, si vas a analizar documentos, `GEMINI_API_KEY`.
3. Desde el directorio del backend, conecta `psql` con los datos del mismo panel. Por ejemplo, para **Session pooler**:

   ```bash
   psql "host=HOST_DEL_POOLER port=5432 dbname=postgres user=postgres.REFERENCIA_DEL_PROYECTO sslmode=require" -v ON_ERROR_STOP=1
   ```

   `psql` solicita la contraseña sin escribirla en el comando. Dentro de `psql`, ejecuta en orden:

   ```text
   \i sql/001_init.sql
   \i sql/migrations/002_auth_lockout.sql
   \i sql/migrations/003_usernames.sql
   \i sql/migrations/004_course_status.sql
   \i sql/migrations/005_activity_types.sql
   \i sql/migrations/006_document_duplicates.sql
   \i sql/migrations/007_document_drafts.sql
   \i sql/migrations/008_session_and_request_limits.sql
   \q
   ```

4. Reinicia FastAPI desde el directorio del backend. Comprueba `http://localhost:8000/api/health` y registra una cuenta desde la interfaz; el registro confirma además la conexión a la base. Si el frontend corre en otra dirección, actualiza `CORS_ORIGINS` en el backend y `NEXT_PUBLIC_API_URL` en el frontend.

Con la configuración actual, evita el **Transaction pooler**: su modo de transacción no admite las sentencias preparadas que puede usar el cliente PostgreSQL. Tampoco pongas la contraseña de la base en `.env.local` del frontend.

Después de crear una cuenta mediante la opción «Crear una cuenta» de la pantalla de inicio, puedes poblarla opcionalmente con datos sintéticos para revisar el tablero sin IA: `python -m app.seed_demo_data tu-correo@ejemplo.com`. El curso y sus cuatro actividades llevan prefijo `DEMO`; no vienen de documentos reales ni de una respuesta simulada del proveedor, y volver a ejecutar el comando no duplica el curso. Para crear cuentas de desarrollo desde la terminal, también puedes usar `python -m app.create_user usuario correo@ejemplo.com`; se solicita la contraseña de forma interactiva. El análisis acepta PDF con texto, Word `.docx` y TXT, máximo 15 MB por archivo; PDFs escaneados requieren OCR y Word `.doc` debe guardarse como `.docx`. El análisis real usa Gemini cuando se configura `GEMINI_API_KEY` en el `.env` del backend; `GEMINI_MODEL` permite elegir el modelo y usa `gemini-3.5-flash-lite` por defecto. La conexión utiliza el endpoint compatible de Google con la librería existente (`openai`), y la clave permanece en el backend. Reinicia el backend después de cambiar el `.env`; sin clave devuelve error explicativo y no crea extracción de prueba.

## Privacidad

Todas las consultas y mutaciones están acotadas al usuario autenticado. No se guardan los archivos subidos; solo metadatos y propuestas confirmadas. No incluyas documentos reales, `.env`, claves ni contraseñas en Git.

## Clúster local de desarrollo de esta máquina

En esta máquina la base persistente está en `~/proyectos/.gestor-tareas-pg`, aislada de los repositorios. La base es `gestor_tareas`, escucha solo en localhost por el puerto `5434`, y FastAPI se conecta con el rol limitado `gestor_app` mediante el `.env` local. El clúster y el `.env` no se versionan. Para administrarlo:

```bash
cd ~/proyectos/GestorDeTarea_Backend
./scripts/dev-db.sh status
./scripts/dev-db.sh stop
./scripts/dev-db.sh start
```

Para inspeccionar el esquema en esta cuenta local, conecta con `psql -h /tmp -p 5434 -U emerson -d gestor_tareas`; dentro de `psql` usa `\dt` y `\d activities`. En otra máquina, instala PostgreSQL y Python como se indica arriba, prepara su propio rol/base `.env` y aplica las migraciones SQL; no copies el `.env` de esta máquina.

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

Con PostgreSQL de desarrollo activo y `.env` apuntando a una base vacía con la migración aplicada, ejecuta `pytest`. Las pruebas crean datos temporales con correo `.invalid` y los eliminan al finalizar. Comprueban registro, hash seguro, requisitos de contraseña, login, bloqueo temporal tras tres fallos, aislamiento por usuario, filtros inclusivos, orden de próximas tareas, estado completado persistente e idempotencia de confirmación; no llaman al proveedor de IA.

### Registro y acceso

La pantalla permite crear una cuenta con correo, nombre de usuario y contraseña. El inicio de sesión usa el nombre de usuario y la contraseña; el correo queda reservado para identificar la cuenta y una futura recuperación. El backend normaliza correo y usuario, exige contraseña de 8 a 128 caracteres, bloquea contraseñas comunes seleccionadas, compara la confirmación y almacena únicamente un hash Argon2id. La interfaz muestra los requisitos y coincidencia en vivo; toda validación se repite en el servidor.

Tras tres contraseñas incorrectas, el inicio de sesión queda bloqueado durante 15 minutos. El bloqueo es temporal y se restablece tras un acceso correcto. El umbral y la duración son decisiones del producto; este bloqueo por cuenta puede permitir que terceros provoquen una espera temporal si conocen un usuario.

En bases existentes, aplica la migración `sql/migrations/002_auth_lockout.sql` antes de iniciar la versión nueva:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/migrations/002_auth_lockout.sql
```
