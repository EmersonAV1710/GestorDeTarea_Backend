# Contrato HTTP v1
Base local: `http://localhost:8000/api`. JSON UTF-8; fechas `YYYY-MM-DD`; UUID en campos `id`. Error estándar FastAPI `{ "detail": "..." }`. Bearer JWT para endpoints privados; registro y login son públicos.

- `POST /auth/register` JSON `{email,username,password,password_confirmation}` → `{message,username}` (201). Correo y usuario se normalizan a minúsculas; el usuario admite 3–30 caracteres (`a-z`, `0-9`, punto, guion y guion bajo). La contraseña debe tener 8–128 caracteres y la confirmación debe coincidir. Correo o usuario ocupado: 409.
- `POST /auth/login` JSON `{username,password}` → `{access_token,token_type,username}`. Credenciales incorrectas: 401 con intentos restantes; después de tres fallos: 429 y bloqueo temporal de 15 minutos.
- `GET /courses` → `[{id,name,code,term}]`; `POST /courses` JSON `{name,code?,term?}` → curso (201).
- `POST /documents/analyze` multipart `course_id`, `file` (PDF hasta 15 MB) → `{document_id,proposals:[{title,description,due_date,review_required}]}`. Una fecha dudosa es `null` y se marca para revisión. Requiere clave de IA real; 422 para PDF sin texto, 503 si falta proveedor.
- `POST /activities/confirm` JSON `{document_id,activities:[{title,description,due_date,review_required}]}` → actividades creadas; repetir la confirmación del mismo documento devuelve las actividades ya creadas sin duplicarlas. Solo este endpoint persiste propuestas.
- `GET /activities?course_id=&date_from=&date_to=&upcoming=` → actividades del usuario; los extremos de fecha son inclusivos y upcoming solo pendientes con fecha >= hoy, ascendente.
- `PATCH /activities/{id}/complete` → actividad actualizada.

El servidor comprueba propietario en cada recurso. El frontend consume exclusivamente esta API; CORS se configura con `CORS_ORIGINS`.

## Validación de análisis y confirmación

El análisis devuelve también `source_excerpt` en cada propuesta: un fragmento del
texto extraído del PDF, comprobado por el servidor y mostrado durante la revisión.
Este campo no se persiste como parte de la actividad. La confirmación envía solo
`title`, `description`, `due_date` y `review_required`.

Se requieren títulos de 1–240 caracteres después de quitar espacios exteriores,
descripciones de hasta 5000 caracteres (se admite `""`, no `null`), fechas de
calendario `YYYY-MM-DD` o `null`, y booleanos reales. Una actividad sin fecha se
marca siempre para revisión. La confirmación admite de 1 a 200 actividades.

PDFs cuyo texto extraído supera 50 000 caracteres se rechazan con 422 antes de
llamar al proveedor; no se analiza un fragmento silenciosamente. Dividirlos permite
analizar su contenido completo. Un análisis sin actividades devuelve 200 con
`proposals: []`. Respuestas inválidas, rechazadas o incompletas del proveedor
devuelven 502; un timeout devuelve 504. No se guarda el documento ni actividades
si la extracción falla. Las propuestas siguen guardándose solo al confirmar.

La confirmación bloquea la fila del documento durante la transacción para que dos
confirmaciones simultáneas del mismo documento no creen dos lotes. Volver a subir
el PDF crea otro documento; no se deduplican cargas distintas.
