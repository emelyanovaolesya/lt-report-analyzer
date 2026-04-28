import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine, session_scope
from app.models import ReportTemplate, User
from app.services.security import get_password_hash
from app.services.template_storage import TEMPLATE_STORAGE_DIR, ensure_template_storage_dir, resolve_storage_path, to_storage_path


@asynccontextmanager
async def lifespan(_: FastAPI):
    """При старте приложения подготавливает БД и начальные данные."""
    wait_for_database()
    Base.metadata.create_all(bind=engine)
    apply_schema_updates()
    seed_default_admin()
    seed_default_report_templates()
    yield


def wait_for_database(retries: int = 20, delay_seconds: int = 2) -> None:
    """Небольшое ожидание БД, чтобы приложение не упало при раннем старте."""
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


def seed_default_admin() -> None:
    """Создает администратора по умолчанию, если его еще нет в базе."""
    with session_scope() as session:
        existing_admin = session.query(User).filter(User.login == settings.default_admin_login).first()
        if existing_admin:
            return

        session.add(
            User(
                login=settings.default_admin_login,
                email="admin@example.local",
                password_hash=get_password_hash(settings.default_admin_password),
                role="ADMIN",
            )
        )


def apply_schema_updates() -> None:
    """Применяет изменения схемы, которые нужны для текущей версии проекта."""
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ALTER COLUMN project_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE load_profiles ALTER COLUMN project_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS second_test_run_id INTEGER"))
        connection.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_type VARCHAR(32) DEFAULT 'TARGET'"))
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint constraint_item
                        JOIN pg_class table_item ON table_item.oid = constraint_item.conrelid
                        JOIN pg_attribute attribute_item
                          ON attribute_item.attrelid = table_item.oid
                         AND attribute_item.attnum = ANY (constraint_item.conkey)
                        WHERE table_item.relname = 'reports'
                          AND attribute_item.attname = 'second_test_run_id'
                          AND constraint_item.contype = 'f'
                    ) THEN
                        ALTER TABLE reports
                        ADD CONSTRAINT fk_reports_second_test_run_id
                        FOREIGN KEY (second_test_run_id) REFERENCES test_runs (id);
                    END IF;
                END $$;
                """
            )
        )


def seed_default_report_templates() -> None:
    """Добавляет базовые шаблоны отчетов для первого запуска системы."""
    ensure_template_storage_dir()

    template_files = {
        "Шаблон целевого теста": TEMPLATE_STORAGE_DIR / "target_test_report.html",
        "Шаблон сравнительного отчета": TEMPLATE_STORAGE_DIR / "comparative_report.html",
    }

    for template_name, template_path in template_files.items():
        if not template_path.exists():
            raise FileNotFoundError(f"Не найден обязательный шаблон отчета: {template_name} ({template_path})")

    with session_scope() as session:
        normalize_template_paths(session)

        if session.query(ReportTemplate).count() == 0:
            session.add_all(
                [
                    ReportTemplate(name=name, file_path=to_storage_path(path))
                    for name, path in template_files.items()
                ]
            )


def normalize_template_paths(session) -> None:
    """Приводит пути к шаблонам к единому виду хранения."""
    for template_item in session.query(ReportTemplate).all():
        current_path = resolve_storage_path(template_item.file_path)
        try:
            template_item.file_path = to_storage_path(current_path)
        except ValueError:
            file_name = current_path.name
            target_path = TEMPLATE_STORAGE_DIR / file_name
            if current_path.exists() and current_path != target_path:
                target_path.write_bytes(current_path.read_bytes())
            template_item.file_path = to_storage_path(target_path)
        session.add(template_item)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
