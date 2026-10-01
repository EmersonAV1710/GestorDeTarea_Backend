import getpass,sys
from sqlalchemy import select
from .db import SessionLocal
from .models import User
from .security import hash_password
def main():
    if len(sys.argv)!=2: raise SystemExit("Uso: python -m app.create_user correo@ejemplo.com")
    email=sys.argv[1].strip().lower(); password=getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if len(password)<12: raise SystemExit("La contraseña debe tener al menos 12 caracteres")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==email)): raise SystemExit("Ese correo ya existe")
        db.add(User(email=email,password_hash=hash_password(password))); db.commit()
    print("Cuenta local creada.")
if __name__=="__main__": main()
