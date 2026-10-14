from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Activity, ActivityReminder, Course, User
from app.reminders import send_due_reminders


def database():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def add_activity(factory, today, title="Examen", status="pending", active=True, days=2):
    with factory() as db:
        user = User(id=uuid4(), email=f"{uuid4()}@example.invalid", username=str(uuid4())[:30], password_hash="unused")
        course = Course(id=uuid4(), user_id=user.id, name="Matemática", is_active=active)
        db.add_all([user, course])
        db.flush()
        db.add(Activity(user_id=user.id, course_id=course.id, title=title,
                        due_date=today + timedelta(days=days), status=status))
        db.commit()


def test_reminders_filter_and_do_not_repeat():
    engine, factory = database()
    today = date(2026, 10, 13)
    add_activity(factory, today)
    add_activity(factory, today, "Hecha", status="completed")
    add_activity(factory, today, "Después", days=3)
    add_activity(factory, today, "Pausada", active=False)
    messages = []
    assert send_due_reminders(factory, today, lambda *args: messages.append(args)) == 1
    assert len(messages) == 1
    assert messages[0][1:] == ("Examen", "Matemática", date(2026, 10, 15))
    assert send_due_reminders(factory, today, lambda *args: messages.append(args)) == 0
    with factory() as db:
        assert len(db.scalars(select(ActivityReminder)).all()) == 1
    engine.dispose()


def test_failed_delivery_can_retry():
    engine, factory = database()
    today = date(2026, 10, 13)
    add_activity(factory, today)

    def fail(*args):
        raise OSError("SMTP no disponible")

    assert send_due_reminders(factory, today, fail) == 0
    assert send_due_reminders(factory, today, lambda *args: None) == 1
    engine.dispose()
