from datetime import date,datetime,timedelta,timezone
from uuid import UUID
from hashlib import sha256
import unicodedata
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File,Form,Header,Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import Base,engine,get_db
from .models import User,Course,Document,Activity,RevokedToken
from .schemas import Login,RegisterIn,CourseIn,CourseOut,ConfirmIn,ManualActivityIn,ActivityType,ActivityUpdate
from .security import verify_password,hash_password,token_for,user_id,token_digest,token_claims
from .request_limits import enforce_request_limits, conflict_insert
from .ai import extract_activities, AnalysisError
from .document_text import extract_document_text
app=FastAPI(title="Gestor de tareas API",version="1.0.0",dependencies=[Depends(enforce_request_limits)])
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],allow_credentials=True,allow_methods=["*"] ,allow_headers=["*"])
def current_user(authorization:str|None=Header(default=None),db:Session=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Inicia sesión")
    try: uid=UUID(user_id(authorization[7:]))
    except ValueError: raise HTTPException(401,"Sesión inválida o vencida")
    if db.get(RevokedToken,token_digest(authorization[7:])) is not None:
        raise HTTPException(401,"Esta sesión fue cerrada. Inicia sesión de nuevo.")
    user=db.get(User,uid)
    if not user: raise HTTPException(401,"Cuenta no encontrada")
    return user
def course_dict(c): return {"id":c.id,"name":c.name,"code":c.code,"term":c.term,"is_active":c.is_active}
def activity_dict(a): return {"activity_type":a.activity_type,"id":a.id,"title":a.title,"description":a.description,"due_date":a.due_date,"review_required":a.review_required,"status":a.status,"course_id":a.course_id,"document_id":a.document_id}
@app.get("/api/health")
def health(): return {"status":"ok"}
@app.post("/api/auth/register",status_code=201)
def register(body:RegisterIn,db:Session=Depends(get_db)):
    if body.password != body.password_confirmation:
        raise HTTPException(422,"Las contraseñas no coinciden")
    if db.scalar(select(User).where((User.email==body.email)|(User.username==body.username))):
        raise HTTPException(409,"El correo o el nombre de usuario ya están registrados.")
    user=User(email=body.email,username=body.username,password_hash=hash_password(body.password))
    db.add(user)
    try: db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409,"El correo o el nombre de usuario ya están registrados.")
    return {"message":"Cuenta creada. Ya puedes iniciar sesión.","username":user.username}
@app.post("/api/auth/login")
def login(body:Login,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.username==body.username).with_for_update())
    now=datetime.now(timezone.utc)
    if not u:
        raise HTTPException(401,"Usuario o contraseña incorrectos.")
    locked_until = u.locked_until.replace(tzinfo=timezone.utc) if u.locked_until and u.locked_until.tzinfo is None else u.locked_until
    if locked_until and locked_until > now:
        remaining=max(1,int((locked_until-now).total_seconds()//60)+1)
        raise HTTPException(429,f"Se agotaron los 3 intentos. Prueba de nuevo en {remaining} minuto(s).")
    if not verify_password(body.password,u.password_hash):
        u.failed_login_attempts += 1
        if u.failed_login_attempts >= 3:
            u.failed_login_attempts=0
            u.locked_until=now+timedelta(minutes=15)
            db.commit()
            raise HTTPException(429,"Se agotaron los 3 intentos. La cuenta se bloqueó temporalmente por 15 minutos.")
        remaining=3-u.failed_login_attempts
        db.commit()
        raise HTTPException(401,f"Usuario o contraseña incorrectos. Te quedan {remaining} intento(s).")
    u.failed_login_attempts=0
    u.locked_until=None
    db.commit()
    return {"access_token":token_for(str(u.id)),"token_type":"bearer","username":u.username}
@app.post("/api/auth/logout", status_code=204)
def logout(user: User = Depends(current_user), authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Response:
    token = authorization[7:]
    try:
        claims = token_claims(token)
    except ValueError as exc:
        raise HTTPException(401, "Sesión inválida o vencida") from exc
    expires_at = datetime.fromtimestamp(claims["exp"], timezone.utc)
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= datetime.now(timezone.utc)))
    statement = conflict_insert(db, RevokedToken).values(token_hash=token_digest(token), expires_at=expires_at).on_conflict_do_nothing(index_elements=[RevokedToken.token_hash])
    db.execute(statement)
    db.commit()
    return Response(status_code=204)


@app.get("/api/courses")
def courses(user:User=Depends(current_user),db:Session=Depends(get_db)): return [course_dict(c) for c in db.scalars(select(Course).where(Course.user_id==user.id).order_by(Course.name))]
@app.post("/api/courses",status_code=201)
def add_course(body:CourseIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    c=Course(user_id=user.id,**body.model_dump());db.add(c)
    try: db.commit();db.refresh(c)
    except IntegrityError: db.rollback();raise HTTPException(409,"Ya existe un curso con ese nombre")
    return course_dict(c)

def owned_course(course_id:UUID,user:User,db:Session)->Course:
    course=db.scalar(select(Course).where(Course.id==course_id,Course.user_id==user.id))
    if course is None: raise HTTPException(404,"Curso no encontrado")
    return course

@app.patch("/api/courses/{course_id}")
def update_course(course_id:UUID,body:CourseIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    course=owned_course(course_id,user,db)
    course.name=body.name
    course.code=body.code
    course.term=body.term
    try: db.commit();db.refresh(course)
    except IntegrityError: db.rollback();raise HTTPException(409,"Ya existe un curso con ese nombre")
    return course_dict(course)

@app.delete("/api/courses/{course_id}")
def deactivate_course(course_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    course=owned_course(course_id,user,db)
    course.is_active=False
    db.commit();db.refresh(course)
    return course_dict(course)

@app.delete("/api/courses/{course_id}/permanent", status_code=204)
def delete_empty_course(course_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    lock_activity_owner(user,db)
    course=db.scalar(select(Course).where(Course.id==course_id,Course.user_id==user.id).with_for_update())
    if course is None:
        raise HTTPException(404,"Curso no encontrado")
    if db.scalar(select(Activity.id).where(Activity.course_id==course.id).limit(1)):
        raise HTTPException(409,"Este curso tiene actividades. Desactívalo para conservarlas.")
    db.execute(delete(Document).where(Document.course_id==course.id,Document.user_id==user.id))
    db.delete(course)
    db.commit()
    return Response(status_code=204)

@app.patch("/api/courses/{course_id}/activate")
def activate_course(course_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    course=owned_course(course_id,user,db)
    course.is_active=True
    db.commit();db.refresh(course)
    return course_dict(course)

def normalized_title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def lock_activity_owner(user: User, db: Session) -> None:
    # Serialize duplicate checks and writes across documents and browser tabs.
    db.scalar(select(User).where(User.id == user.id).with_for_update())


def duplicate_document(user: User, content_hash: str, filename: str, db: Session) -> Document | None:
    documents = db.scalars(select(Document).where(Document.user_id == user.id, (Document.content_hash == content_hash) | Document.content_hash.is_(None)))
    return next((document for document in documents if document.content_hash == content_hash or (
        document.content_hash is None and normalized_title(document.filename) == normalized_title(filename)
    )), None)


def document_dict(document: Document) -> dict:
    return {"document_id": document.id, "course_id": document.course_id, "filename": document.filename,
            "proposals": document.draft_proposals or []}


@app.get("/api/documents/pending")
def pending_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    documents = db.scalars(select(Document).where(Document.user_id == user.id, Document.is_confirmed.is_(False)).order_by(Document.filename, Document.id))
    return [document_dict(document) for document in documents]


@app.get("/api/documents")
def saved_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Document, func.count(Activity.id)).join(Activity, Activity.document_id == Document.id)
        .where(Document.user_id == user.id, Document.is_confirmed.is_(True))
        .group_by(Document.id).order_by(Document.filename, Document.id))
    return [{"document_id": document.id, "course_id": document.course_id, "filename": document.filename,
             "activity_count": count} for document, count in rows]


@app.delete("/api/documents/{document_id}", status_code=204)
def delete_pending_document(document_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id).with_for_update())
    if document is None:
        raise HTTPException(404, "Revisión no encontrada")
    if document.is_confirmed or db.scalar(select(Activity.id).where(Activity.document_id == document.id).limit(1)):
        raise HTTPException(409, "Este documento ya tiene actividades guardadas y no se puede quitar de las revisiones pendientes.")
    db.delete(document)
    db.commit()
    return Response(status_code=204)


@app.delete("/api/documents/{document_id}/saved", status_code=204)
def delete_saved_document(document_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id).with_for_update())
    if document is None:
        raise HTTPException(404, "Documento guardado no encontrado")
    if not document.is_confirmed:
        raise HTTPException(409, "Este documento aún está en revisión.")
    db.execute(delete(Activity).where(Activity.document_id == document.id, Activity.user_id == user.id))
    db.delete(document)
    db.commit()
    return Response(status_code=204)


def reject_confirmed_document(document: Document, user: User, db: Session) -> None:
    if db.scalar(select(Activity.id).where(Activity.document_id == document.id, Activity.user_id == user.id).limit(1)):
        raise HTTPException(409, "Este archivo ya fue guardado. No se puede cargar otra vez.")


def reject_duplicate_activities(proposals, course_id: UUID, user: User, db: Session, exclude_id: UUID | None = None) -> None:
    existing = db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.course_id == course_id))
    keys = {(normalized_title(activity.title), activity.due_date) for activity in existing if activity.id != exclude_id}
    for proposal in proposals:
        key = (normalized_title(proposal.title), proposal.due_date)
        if key in keys:
            raise HTTPException(409, f'La actividad "{proposal.title}" ya existe o está repetida en las propuestas para este curso y fecha. Modifica o descarta la repetida antes de guardar.')
        keys.add(key)


@app.post("/api/documents/analyze")
async def analyze(course_id:UUID=Form(...),file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    course=db.scalar(select(Course).where(Course.id==course_id,Course.user_id==user.id))
    if not course: raise HTTPException(404,"Curso no encontrado")
    if not course.is_active: raise HTTPException(409,"El curso está inactivo. Reactívalo para analizar documentos")
    raw=await file.read(settings.max_pdf_mb*1024*1024+1)
    if len(raw)>settings.max_pdf_mb*1024*1024: raise HTTPException(413,f"El archivo supera {settings.max_pdf_mb} MB")
    filename = (file.filename or "documento").strip()[:240]
    content_hash = sha256(raw).hexdigest()
    duplicate = duplicate_document(user, content_hash, filename, db)
    if duplicate:
        reject_confirmed_document(duplicate, user, db)
        if duplicate.course_id != course.id and not duplicate.is_confirmed:
            raise HTTPException(409, "Este documento pertenece a otro curso. Retoma su revisión desde el curso original.")
        if duplicate.draft_proposals and not duplicate.is_confirmed:
            return document_dict(duplicate)
    try:
        text = await run_in_threadpool(extract_document_text, raw, file.filename or "", file.content_type)
        proposals = await run_in_threadpool(extract_activities, text, settings.gemini_api_key, settings.gemini_model)
    except AnalysisError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    lock_activity_owner(user, db)
    duplicate = duplicate_document(user, content_hash, filename, db)
    if duplicate:
        reject_confirmed_document(duplicate, user, db)
        if duplicate.course_id != course.id and not duplicate.is_confirmed:
            raise HTTPException(409, "Este documento pertenece a otro curso. Retoma su revisión desde el curso original.")
        if duplicate.draft_proposals and not duplicate.is_confirmed:
            return document_dict(duplicate)
    document = duplicate or Document(user_id=user.id, course_id=course.id, filename=filename, status="analyzed")
    document.course_id = course.id
    document.filename = filename
    document.is_confirmed = False
    document.content_hash = content_hash
    document.draft_proposals = proposals
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = duplicate_document(user, content_hash, filename, db)
        if duplicate:
            reject_confirmed_document(duplicate, user, db)
            if duplicate.course_id != course.id and not duplicate.is_confirmed:
                raise HTTPException(409, "Este documento pertenece a otro curso. Retoma su revisión desde el curso original.")
            if duplicate.draft_proposals and not duplicate.is_confirmed:
                return document_dict(duplicate)
        raise
    db.refresh(document)
    return document_dict(document)


@app.post("/api/activities/confirm")
def confirm(body:ConfirmIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    lock_activity_owner(user, db)
    doc=db.scalar(select(Document).where(Document.id==body.document_id,Document.user_id==user.id).with_for_update())
    if not doc: raise HTTPException(404,"Documento no encontrado")
    existing=list(db.scalars(select(Activity).where(Activity.document_id==doc.id,Activity.user_id==user.id)))
    if existing or doc.is_confirmed: return [activity_dict(a) for a in existing]
    reject_duplicate_activities(body.activities, doc.course_id, user, db)
    out=[]
    for p in body.activities:
        a=Activity(user_id=user.id,course_id=doc.course_id,document_id=doc.id,
                   completed_at=datetime.now(timezone.utc) if p.status=="completed" else None,
                   **p.model_dump());db.add(a);out.append(a)
    doc.is_confirmed = True
    doc.draft_proposals = None
    db.commit()
    for a in out: db.refresh(a)
    return [activity_dict(a) for a in out]
@app.get("/api/activities")
def activities(course_id:UUID|None=None,date_from:date|None=None,date_to:date|None=None,upcoming:bool=False,activity_type:ActivityType|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if date_from and date_to and date_from>date_to: raise HTTPException(422,"date_from debe ser anterior o igual a date_to")
    q=select(Activity).where(Activity.user_id==user.id)
    if activity_type: q=q.where(Activity.activity_type==activity_type)
    if course_id: q=q.where(Activity.course_id==course_id)
    if date_from: q=q.where(Activity.due_date>=date_from)
    if date_to: q=q.where(Activity.due_date<=date_to)
    if upcoming: q=q.where(Activity.status=="pending",Activity.due_date>=date.today()).order_by(Activity.due_date.asc())
    else: q=q.order_by(Activity.due_date.asc().nulls_last(),Activity.created_at.desc())
    return [activity_dict(a) for a in db.scalars(q)]

@app.post("/api/activities", status_code=201)
def create_activity(body:ManualActivityIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    lock_activity_owner(user, db)
    course=owned_course(body.course_id,user,db)
    if not course.is_active:
        raise HTTPException(409,"El curso está inactivo. Reactívalo para añadir tareas.")
    reject_duplicate_activities([body],course.id,user,db)
    activity=Activity(user_id=user.id,document_id=None,
                      completed_at=datetime.now(timezone.utc) if body.status=="completed" else None,
                      **body.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity_dict(activity)

def owned_activity(activity_id: UUID, user: User, db: Session) -> Activity:
    activity = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id).with_for_update())
    if activity is None:
        raise HTTPException(404, "Actividad no encontrada")
    return activity

@app.patch("/api/activities/{activity_id}")
def update_activity(activity_id: UUID, body: ActivityUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_activity_owner(user, db)
    activity = owned_activity(activity_id, user, db)
    reject_duplicate_activities([body], activity.course_id, user, db, exclude_id=activity.id)
    for field, value in body.model_dump().items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity_dict(activity)

@app.delete("/api/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    lock_activity_owner(user, db)
    activity = owned_activity(activity_id, user, db)
    document_id = activity.document_id
    db.delete(activity)
    db.flush()
    if document_id and not db.scalar(select(Activity.id).where(Activity.document_id == document_id).limit(1)):
        document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id).with_for_update())
        if document is not None:
            db.delete(document)
    db.commit()
    return Response(status_code=204)

@app.patch("/api/activities/{activity_id}/reopen")
def reopen_activity(activity_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    activity = owned_activity(activity_id, user, db)
    activity.status = "pending"
    activity.completed_at = None
    db.commit()
    db.refresh(activity)
    return activity_dict(activity)

@app.patch("/api/activities/{activity_id}/complete")
def complete(activity_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    a=owned_activity(activity_id,user,db)
    a.status="completed";a.completed_at=datetime.now(timezone.utc);db.commit();db.refresh(a);return activity_dict(a)
