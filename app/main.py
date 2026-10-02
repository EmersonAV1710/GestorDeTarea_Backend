from datetime import date,datetime,timedelta,timezone
from uuid import UUID
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File,Form,Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import Base,engine,get_db
from .models import User,Course,Document,Activity
from .schemas import Login,RegisterIn,CourseIn,CourseOut,ConfirmIn
from .security import verify_password,hash_password,token_for,user_id
app=FastAPI(title="Gestor de tareas API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],allow_credentials=True,allow_methods=["*"] ,allow_headers=["*"])
def current_user(authorization:str|None=Header(default=None),db:Session=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Inicia sesión")
    try: uid=UUID(user_id(authorization[7:]))
    except ValueError: raise HTTPException(401,"Sesión inválida o vencida")
    user=db.get(User,uid)
    if not user: raise HTTPException(401,"Cuenta no encontrada")
    return user
def course_dict(c): return {"id":c.id,"name":c.name,"code":c.code,"term":c.term}
def activity_dict(a): return {"id":a.id,"title":a.title,"description":a.description,"due_date":a.due_date,"review_required":a.review_required,"status":a.status,"course_id":a.course_id,"document_id":a.document_id}
@app.get("/api/health")
def health(): return {"status":"ok"}
@app.post("/api/auth/register",status_code=201)
def register(body:RegisterIn,db:Session=Depends(get_db)):
    if body.password != body.password_confirmation:
        raise HTTPException(422,"Las contraseñas no coinciden")
    if db.scalar(select(User).where(User.email==body.email)):
        raise HTTPException(409,"No se pudo crear la cuenta con esos datos. Verifica el correo o inicia sesión.")
    user=User(email=body.email,password_hash=hash_password(body.password))
    db.add(user)
    try: db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409,"No se pudo crear la cuenta con esos datos. Verifica el correo o inicia sesión.")
    return {"message":"Cuenta creada. Ya puedes iniciar sesión."}
@app.post("/api/auth/login")
def login(body:Login,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==body.email))
    now=datetime.now(timezone.utc)
    if not u:
        raise HTTPException(401,"Correo o contraseña incorrectos.")
    if u.locked_until and u.locked_until > now:
        remaining=max(1,int((u.locked_until-now).total_seconds()//60)+1)
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
        raise HTTPException(401,f"Correo o contraseña incorrectos. Te quedan {remaining} intento(s).")
    u.failed_login_attempts=0
    u.locked_until=None
    db.commit()
    return {"access_token":token_for(str(u.id)),"token_type":"bearer"}
@app.get("/api/courses")
def courses(user:User=Depends(current_user),db:Session=Depends(get_db)): return [course_dict(c) for c in db.scalars(select(Course).where(Course.user_id==user.id).order_by(Course.name))]
@app.post("/api/courses",status_code=201)
def add_course(body:CourseIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    c=Course(user_id=user.id,**body.model_dump());db.add(c)
    try: db.commit();db.refresh(c)
    except Exception: db.rollback();raise HTTPException(409,"Ya existe un curso con ese nombre")
    return course_dict(c)
@app.post("/api/documents/analyze")
async def analyze(course_id:UUID=Form(...),file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    course=db.scalar(select(Course).where(Course.id==course_id,Course.user_id==user.id))
    if not course: raise HTTPException(404,"Curso no encontrado")
    if file.content_type!="application/pdf" and not (file.filename or "").lower().endswith(".pdf"): raise HTTPException(415,"Solo se admite PDF")
    raw=await file.read(settings.max_pdf_mb*1024*1024+1)
    if len(raw)>settings.max_pdf_mb*1024*1024: raise HTTPException(413,f"El PDF supera {settings.max_pdf_mb} MB")
    from pypdf import PdfReader
    import io
    try: text="\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    except Exception: raise HTTPException(422,"No se pudo leer el PDF")
    if not text.strip(): raise HTTPException(422,"El PDF no contiene texto seleccionable; OCR no está habilitado")
    if not settings.openai_api_key: raise HTTPException(503,"Configura OPENAI_API_KEY en el backend para analizar documentos. No se generaron propuestas.")
    from openai import OpenAI
    prompt="Extrae actividades académicas explícitas. Devuelve JSON {activities:[{title,description,due_date (YYYY-MM-DD o null),review_required (boolean)}]}. No inventes fechas; si hay ambigüedad usa null y review_required=true. Texto:\n"+text[:50000]
    try:
        result=OpenAI(api_key=settings.openai_api_key).chat.completions.create(model=settings.openai_model,response_format={"type":"json_object"},messages=[{"role":"system","content":"Eres un extractor conservador de tareas. Responde solo JSON."},{"role":"user","content":prompt}])
        import json
        proposals=json.loads(result.choices[0].message.content or "{}").get("activities",[])
    except Exception as e: raise HTTPException(502,"Falló el análisis con el proveedor de IA; verifica configuración e inténtalo de nuevo") from e
    d=Document(user_id=user.id,course_id=course.id,filename=(file.filename or "documento.pdf")[:240],status="analyzed");db.add(d);db.flush();db.commit()
    return {"document_id":d.id,"proposals":proposals}
@app.post("/api/activities/confirm")
def confirm(body:ConfirmIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    doc=db.scalar(select(Document).where(Document.id==body.document_id,Document.user_id==user.id))
    if not doc: raise HTTPException(404,"Documento no encontrado")
    existing=list(db.scalars(select(Activity).where(Activity.document_id==doc.id,Activity.user_id==user.id)))
    if existing: return [activity_dict(a) for a in existing]
    out=[]
    for p in body.activities:
        a=Activity(user_id=user.id,course_id=doc.course_id,document_id=doc.id,**p.model_dump());db.add(a);out.append(a)
    db.commit()
    for a in out: db.refresh(a)
    return [activity_dict(a) for a in out]
@app.get("/api/activities")
def activities(course_id:UUID|None=None,date_from:date|None=None,date_to:date|None=None,upcoming:bool=False,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if date_from and date_to and date_from>date_to: raise HTTPException(422,"date_from debe ser anterior o igual a date_to")
    q=select(Activity).where(Activity.user_id==user.id)
    if course_id: q=q.where(Activity.course_id==course_id)
    if date_from: q=q.where(Activity.due_date>=date_from)
    if date_to: q=q.where(Activity.due_date<=date_to)
    if upcoming: q=q.where(Activity.status=="pending",Activity.due_date>=date.today()).order_by(Activity.due_date.asc())
    else: q=q.order_by(Activity.due_date.asc().nulls_last(),Activity.created_at.desc())
    return [activity_dict(a) for a in db.scalars(q)]
@app.patch("/api/activities/{activity_id}/complete")
def complete(activity_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    a=db.scalar(select(Activity).where(Activity.id==activity_id,Activity.user_id==user.id))
    if not a: raise HTTPException(404,"Actividad no encontrada")
    a.status="completed";a.completed_at=datetime.now(timezone.utc);db.commit();db.refresh(a);return activity_dict(a)
