"""Recordatorios por correo para actividades que vencen en dos días."""
import asyncio
import logging
import smtplib
import ssl
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Activity, ActivityReminder, Course, User

logger = logging.getLogger(__name__)


def send_reminder(recipient: str, title: str, course: str, due_date) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = "Recordatorio: actividad en 2 días"
    message.set_content(
        f"Hola:\n\nLa actividad «{title}» del curso «{course}» vence el "
        f"{due_date:%d/%m/%Y}. Faltan 2 días para su fecha de entrega.\n\n"
        "Este es un aviso automático del Gestor de Tareas.\n"
    )
    smtp_class = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=15,
                    **({"context": ssl.create_default_context()} if settings.smtp_use_ssl else {})) as smtp:
        if not settings.smtp_use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def send_due_reminders(session_factory=SessionLocal, today=None, send=send_reminder) -> int:
    """Envía una vez por actividad y fecha; los errores quedan disponibles para reintento."""
    if today is None:
        today = datetime.now(ZoneInfo(settings.reminder_timezone)).date()
    target = today + timedelta(days=2)
    with session_factory() as db:
        ids = db.scalars(
            select(Activity.id).join(Course, Course.id == Activity.course_id)
            .where(Activity.due_date == target, Activity.status == "pending", Course.is_active.is_(True))
        ).all()

    sent = 0
    for activity_id in ids:
        with session_factory() as db:
            try:
                # El bloqueo y el registro evitan duplicados entre procesos simultáneos.
                activity = db.scalar(
                    select(Activity).where(Activity.id == activity_id)
                    .with_for_update(skip_locked=True)
                )
                if activity is None or activity.status != "pending" or activity.due_date != target:
                    continue
                course = db.get(Course, activity.course_id)
                if course is None or not course.is_active:
                    continue
                if db.get(ActivityReminder, (activity.id, target)) is not None:
                    continue
                user = db.get(User, activity.user_id)
                if user is None:
                    continue
                send(user.email, activity.title, course.name, target)
                db.add(ActivityReminder(activity_id=activity.id, due_date=target))
                db.commit()
                sent += 1
            except Exception:
                db.rollback()
                logger.exception("No se pudo enviar el recordatorio de la actividad %s", activity_id)
    return sent


async def reminder_loop() -> None:
    while True:
        try:
            if settings.smtp_host and settings.smtp_from_email:
                await asyncio.to_thread(send_due_reminders)
        except Exception:
            logger.exception("Falló la ejecución de recordatorios")
        await asyncio.sleep(3600)


@asynccontextmanager
async def reminder_lifespan(app):
    task = asyncio.create_task(reminder_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
