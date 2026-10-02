import getpass,sys
from sqlalchemy import select
from .db import SessionLocal
from .models import User
from .security import hash_password
from .schemas import normalize_email,normalize_username,validate_password
def main():
    if len(sys.argv)!=3: raise SystemExit("Uso: python -m app.create_user usuario correo@ejemplo.com")
    try:
        username=normalize_username(sys.argv[1]); email=normalize_email(sys.argv[2])
    except ValueError as e: raise SystemExit(str(e))
    password=getpass.getpass("Contraseña (mínimo 8 caracteres): ")
    try: validate_password(password)
    except ValueError as e: raise SystemExit(str(e))
    with SessionLocal() as db:
        if db.scalar(select(User).where((User.email==email)|(User.username==username))): raise SystemExit("Ese correo o usuario ya existe")
        db.add(User(email=email,username=username,password_hash=hash_password(password))); db.commit()
    print("Cuenta local creada.")
if __name__=="__main__": main()
