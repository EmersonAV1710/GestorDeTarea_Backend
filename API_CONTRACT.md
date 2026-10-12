# Contrato HTTP v1
Base local: `http://localhost:8000/api`. JSON UTF-8; fechas `YYYY-MM-DD`; UUID en campos `id`. Error estándar FastAPI `{ "detail": "..." }`. Bearer JWT para endpoints privados; registro y login son públicos.

- `POST /auth/register` JSON `{email,username,password,password_confirmation}` → `{message,username}` (201). Correo y usuario se normalizan a minúsculas; el usuario admite 3–30 caracteres (`a-z`, `0-9`, punto, guion y guion bajo). La contraseña debe tener 8–128 caracteres y la confirmación debe coincidir. Correo o usuario ocupado: 409.
- `POST /auth/login` JSON `{username,password}` → `{access_token,token_type,username}`. Credenciales incorrectas: 401 con intentos restantes; después de tres fallos: 429 y bloqueo temporal de 15 minutos.
- `GET /courses` → `[{id,name,code,term,is_active}]`, incluidos los inactivos para conservar el historial. `POST /courses` JSON `{name,code?,term?}` → curso activo (201).
- `PATCH /courses/{id}` JSON `{name,code?,term?}` → curso actualizado. `DELETE /courses/{id}` → curso con `is_active: false`, sin borrar tareas ni documentos. `PATCH /courses/{id}/activate` → curso reactivado. Los tres requieren ser propietario; un nombre duplicado devuelve 409.
- `POST /documents/analyze` multipart `course_id`, `file` (PDF, DOCX o TXT hasta 15 MB) → `{document_id,proposals:[{title,description,activity_type,due_date,review_required,source_excerpt}]}`. El curso debe estar activo; si está inactivo devuelve 409. Una fecha dudosa es `null` y se marca para revisión. Requiere clave de IA real; 422 para archivos sin texto legible, 503 si falta proveedor. Word antiguo `.doc` no está admitido.
- `GET /documents/pending` → revisiones sin confirmar del usuario. `DELETE /documents/{id}` → elimina una revisión pendiente y devuelve 204; devuelve 404 si no pertenece al usuario y 409 si el documento ya tiene actividades guardadas.
- `GET /documents` → `[{document_id,course_id,filename,activity_count}]` para documentos confirmados con actividades. Al borrar la última actividad de un documento se elimina su registro y el mismo archivo puede analizarse de nuevo.
- `POST /activities/confirm` JSON `{document_id,activities:[{title,description,activity_type,due_date,review_required,status?}]}` → actividades creadas; `status` admite `pending` (por defecto) o `completed`. Una propuesta con fecha pasada puede guardarse como vencida (`pending`) o entregada (`completed`). Repetir la confirmación del mismo documento devuelve las actividades ya creadas sin duplicarlas. Solo este endpoint persiste propuestas.
- `POST /activities` JSON `{course_id,title,description?,activity_type?,due_date?,review_required?,status?}` → actividad manual (201), sin documento asociado. Requiere un curso propio y activo; rechaza duplicados de título y fecha en el curso.
- `GET /activities?course_id=&activity_type=&date_from=&date_to=&upcoming=` → actividades del usuario; los extremos de fecha son inclusivos y upcoming solo pendientes con fecha >= hoy, ascendente.
- `PATCH /activities/{id}/complete` → actividad actualizada.

El servidor comprueba propietario en cada recurso. El frontend consume exclusivamente esta API; CORS se configura con `CORS_ORIGINS`.

## Validación de análisis y confirmación

El análisis devuelve también `source_excerpt` en cada propuesta: un fragmento del
texto extraído del archivo, comprobado por el servidor y mostrado durante la revisión.
Si falla la cita de alguna propuesta pero hay otras verificadas, la propuesta dudosa
se entrega con `source_excerpt: ""`, `due_date: null` y `review_required: true` para
que el usuario la compruebe o descarte. Si no se verifica ninguna, el análisis falla.
Este campo no se persiste como parte de la actividad. La confirmación envía solo
`title`, `description`, `activity_type`, `due_date`, `review_required` y `status`.

Se requieren títulos de 1–240 caracteres después de quitar espacios exteriores,
descripciones de hasta 5000 caracteres (se admite `""`, no `null`), fechas de
calendario `YYYY-MM-DD` o `null`, y booleanos reales. Una actividad sin fecha se
marca siempre para revisión. La confirmación admite de 1 a 200 actividades.

Documentos cuyo texto extraído supera 50 000 caracteres se rechazan con 422 antes de
llamar al proveedor; no se analiza un fragmento silenciosamente. Dividirlos permite
analizar su contenido completo. Un análisis sin actividades devuelve 200 con
`proposals: []`. Respuestas inválidas, rechazadas o incompletas del proveedor
devuelven 502; un timeout devuelve 504. No se guarda el documento ni actividades
si la extracción falla. Las propuestas siguen guardándose solo al confirmar.

La confirmación bloquea la fila del documento durante la transacción para que dos
confirmaciones simultáneas del mismo documento no creen dos lotes. Un archivo con
actividades guardadas no se vuelve a analizar hasta eliminar esas actividades.

`activity_type` admite `tarea`, `proyecto`, `examen`, `exposicion`, `laboratorio`, `lectura` y `otro`. La IA debe proponer un tipo válido; la confirmación conserva `otro` como valor compatible si no se envía. Los registros anteriores se conservan como `otro`. El filtro de actividades exige un tipo válido.

- `PATCH /activities/{id}` JSON `{title,description,activity_type,due_date,review_required}` → actividad actualizada. Mantiene curso, documento y estado. Los campos ajenos al formulario se rechazan con 422.
- `DELETE /activities/{id}` → 204, borra únicamente la actividad; conserva el documento y el curso.
- `PATCH /activities/{id}/reopen` → actividad pendiente con `completed_at: null`.
Estas operaciones y completar una actividad exigen autenticación y propiedad; un recurso ajeno o inexistente devuelve 404.

La evidencia admite diferencias de formato entre saltos de línea de una tabla PDF y separadores `|` de la respuesta. Las palabras, fechas, signos restantes y su orden deben coincidir en un tramo continuo. El fragmento mostrado se recupera del texto original del documento.

La lectura reconoce MIME de PDF, DOCX y TXT si falta su extensión. TXT admite UTF-8, Windows-1252 y UTF-16/UTF-32 con marca de codificación. PDF protegido requiere una copia desbloqueada. La evidencia admite comillas tipográficas, ligaduras y acentos compuestos equivalentes, recuperando el tramo original; no admite palabras inventadas, fechas distintas ni cambios de orden.
