"""Create clearly labeled local-only sample records for the dashboard preview."""
import argparse
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .db import SessionLocal
from .models import Activity, Course, User

DEMO_COURSE = "DEMO · Curso de ejemplo"


def main() -> None:
    parser = argparse.ArgumentParser(description="Añade datos sintéticos marcados DEMO a una cuenta local.")
    parser.add_argument("email", help="Correo de una cuenta ya creada en la base local")
    args = parser.parse_args()

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if user is None:
            raise SystemExit("No existe esa cuenta. Créala primero con `python -m app.create_user correo`.")
        course = db.scalar(select(Course).where(Course.user_id == user.id, Course.name == DEMO_COURSE))
        if course is not None:
            print("Los datos DEMO ya existen para esta cuenta. No se duplicaron.")
            return

        course = Course(user_id=user.id, name=DEMO_COURSE, code="DEMO-01", term="Datos sintéticos")
        db.add(course)
        db.flush()
        today = date.today()
        db.add_all([
            Activity(user_id=user.id, course_id=course.id, title="DEMO · Entrega próxima", description="Actividad sintética para probar el orden del tablero.", due_date=today + timedelta(days=2)),
            Activity(user_id=user.id, course_id=course.id, title="DEMO · Quiz de muestra", description="Dato ficticio. No proviene de un documento académico.", due_date=today + timedelta(days=6)),
            Activity(user_id=user.id, course_id=course.id, title="DEMO · Actividad completada", description="Registro sintético para revisar el estado completado.", due_date=today - timedelta(days=2), status="completed", completed_at=datetime.now(timezone.utc)),
            Activity(user_id=user.id, course_id=course.id, title="DEMO · Fecha por revisar", description="La fecha se deja vacía para mostrar actividades sin fecha confirmada.", due_date=None, review_required=True),
        ])
        db.commit()
        print("Curso DEMO y cuatro actividades sintéticas creados. No son una extracción de IA.")


if __name__ == "__main__":
    main()
