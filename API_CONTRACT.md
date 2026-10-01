# Contrato HTTP v1
Base local: `http://localhost:8000/api`. JSON UTF-8; fechas `YYYY-MM-DD`; UUID en campos `id`. Error estándar FastAPI `{ "detail": "..." }`. Bearer JWT en todos los endpoints salvo login.

- `POST /auth/login` JSON `{email,password}` → `{access_token,token_type}`. Rechazo 401. No existe registro público.
- `GET /courses` → `[{id,name,code,term}]`; `POST /courses` JSON `{name,code?,term?}` → curso (201).
- `POST /documents/analyze` multipart `course_id`, `file` (PDF hasta 15 MB) → `{document_id,proposals:[{title,description,due_date,review_required}]}`. Una fecha dudosa es `null` y se marca para revisión. Requiere clave de IA real; 422 para PDF sin texto, 503 si falta proveedor.
- `POST /activities/confirm` JSON `{document_id,activities:[{title,description,due_date,review_required}]}` → actividades creadas; repetir la confirmación del mismo documento devuelve las actividades ya creadas sin duplicarlas. Solo este endpoint persiste propuestas.
- `GET /activities?course_id=&date_from=&date_to=&upcoming=` → actividades del usuario; los extremos de fecha son inclusivos y upcoming solo pendientes con fecha >= hoy, ascendente.
- `PATCH /activities/{id}/complete` → actividad actualizada.

El servidor comprueba propietario en cada recurso. El frontend consume exclusivamente esta API; CORS se configura con `CORS_ORIGINS`.
