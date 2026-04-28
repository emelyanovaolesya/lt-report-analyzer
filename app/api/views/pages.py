from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_role
from app.models import LoadProfile, LoadProfileOperation, Project, Report, ReportTemplate, TestRun, User
from app.services.report_service import ReportService
from app.services.security import get_password_hash
from app.services.template_storage import TEMPLATE_STORAGE_DIR, ensure_template_storage_dir, resolve_storage_path, to_storage_path


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ROLE_LABELS = {
    "ADMIN": "Администратор",
    "ENGINEER": "Инженер НТ",
    "CUSTOMER": "Заказчик НТ",
}
REPORT_TYPE_TARGET = "TARGET"
REPORT_TYPE_COMPARATIVE = "COMPARATIVE"
GRAFANA_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_redirect(url: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    """Редирект с сообщением об успехе или ошибке через query-параметры."""
    query = {}
    if message:
        query["message"] = message
    if error:
        query["error"] = error
    if query:
        url = f"{url}?{urlencode(query)}"
    return RedirectResponse(url=url, status_code=303)


def get_available_projects_for_user(db: Session, current_user: User) -> list[Project]:
    """Возвращает только те проекты, которые доступны текущему пользователю."""
    if current_user.role == "ADMIN":
        return db.query(Project).order_by(Project.name).all()
    if current_user.project_id:
        project = db.get(Project, current_user.project_id)
        return [project] if project else []
    return []


def get_profiles_query(db: Session, current_user: User):
    """Строит базовый запрос профилей с учетом роли пользователя."""
    query = db.query(LoadProfile)
    if current_user.role != "ADMIN":
        if current_user.project_id:
            query = query.filter(LoadProfile.project_id == current_user.project_id)
        else:
            query = query.filter(LoadProfile.project_id.is_(None))
    return query.order_by(LoadProfile.created_at.desc())


def get_available_profiles_for_user(db: Session, current_user: User) -> list[LoadProfile]:
    """Получает список профилей, которые можно показать в интерфейсе."""
    return get_profiles_query(db, current_user).all()


def user_can_access_profile(current_user: User, profile: LoadProfile) -> bool:
    """Проверяет, может ли пользователь работать с выбранным профилем."""
    if current_user.role == "ADMIN":
        return True
    if current_user.project_id:
        return profile.project_id == current_user.project_id
    return profile.project_id is None


def get_available_tests_for_user(db: Session, current_user: User) -> list[TestRun]:
    """Возвращает тесты, доступные пользователю в рамках его роли и проекта."""
    query = db.query(TestRun).join(TestRun.load_profile)
    if current_user.role != "ADMIN":
        if current_user.project_id:
            query = query.filter(LoadProfile.project_id == current_user.project_id)
        else:
            query = query.filter(LoadProfile.project_id.is_(None))
    return query.order_by(TestRun.started_at.desc()).all()


def user_can_access_test(current_user: User, test_run: TestRun) -> bool:
    """Проверяет доступ пользователя к конкретному тестовому прогону."""
    if current_user.role == "ADMIN":
        return True
    profile = test_run.load_profile
    if current_user.project_id:
        return bool(profile and profile.project_id == current_user.project_id)
    return bool(profile and profile.project_id is None)


def get_reports_query(db: Session, current_user: User):
    """Строит запрос отчетов с учетом роли и проектных ограничений."""
    query = db.query(Report)
    if current_user.role != "ADMIN":
        if current_user.project_id:
            query = query.filter(Report.project_id == current_user.project_id)
        else:
            query = query.filter(Report.user_id == current_user.id)
    return query.order_by(Report.created_at.desc())


def user_can_access_report(current_user: User, report: Report) -> bool:
    """Проверяет, можно ли пользователю открыть выбранный отчет."""
    if current_user.role == "ADMIN":
        return True
    if current_user.project_id:
        return report.project_id == current_user.project_id
    return report.user_id == current_user.id


def parse_datetime_value(value: str) -> datetime:
    """Преобразует строку даты из формы в объект datetime."""
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError

    for fmt in (GRAFANA_DATETIME_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(normalized_value, fmt)
        except ValueError:
            continue

    return datetime.fromisoformat(normalized_value)


def get_default_report_template(db: Session, report_type: str) -> ReportTemplate | None:
    """Подбирает стандартный шаблон под нужный тип отчета."""
    target_name = "target_test_report.html" if report_type == REPORT_TYPE_TARGET else "comparative_report.html"
    for template_item in db.query(ReportTemplate).order_by(ReportTemplate.id).all():
        if Path(template_item.file_path).name == target_name:
            return template_item
    return None


def parse_test_form(
    db: Session,
    current_user: User,
    name: str,
    load_profile_id: str,
    started_at: str,
    finished_at: str,
    load_percent: str,
    influx_bucket: str,
    prometheus_url: str,
):
    """Собирает и валидирует данные формы создания или редактирования теста."""
    normalized_name = name.strip()
    if not normalized_name:
        return None, "Нужно указать название теста."

    if not load_profile_id.strip():
        return None, "Нужно выбрать профиль НТ."

    try:
        profile_id_value = int(load_profile_id)
    except ValueError:
        return None, "Некорректный профиль НТ."

    profile = db.get(LoadProfile, profile_id_value)
    if not profile or not user_can_access_profile(current_user, profile):
        return None, "Выбранный профиль НТ недоступен для текущего пользователя."

    try:
        started_dt = parse_datetime_value(started_at)
        finished_dt = parse_datetime_value(finished_at)
    except ValueError:
        return None, "Нужно указать время в формате YYYY-MM-DD HH:MM:SS."

    if finished_dt <= started_dt:
        return None, "Время конца теста должно быть позже времени начала."

    try:
        load_percent_value = int(load_percent)
    except ValueError:
        return None, "Уровень нагрузки должен быть целым числом."

    if load_percent_value < 0:
        return None, "Уровень нагрузки не может быть отрицательным."

    return {
        "name": normalized_name,
        "load_profile_id": profile.id,
        "started_at": started_dt,
        "finished_at": finished_dt,
        "load_percent": load_percent_value,
        "influx_bucket": influx_bucket.strip(),
        "prometheus_url": prometheus_url.strip(),
    }, None


@router.get("/projects")
def projects_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Функция для отображения страницы со списком проектов."""
    projects_query = db.query(Project)
    if current_user.role != "ADMIN":
        if current_user.project_id:
            projects_query = projects_query.filter(Project.id == current_user.project_id)
        else:
            projects_query = projects_query.filter(Project.id == -1)
    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "user": current_user,
            "projects": projects_query.order_by(Project.created_at.desc()).all(),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/projects")
def create_project(
    code: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для создания нового проекта."""
    normalized_code = code.strip()
    normalized_name = name.strip()

    if not normalized_code or not normalized_name:
        return build_redirect("/projects", error="Нужно заполнить код и название проекта.")

    existing = (
        db.query(Project)
        .filter((Project.code == normalized_code) | (Project.name == normalized_name))
        .first()
    )
    if existing:
        return build_redirect("/projects", error="Проект с таким кодом или названием уже существует.")

    db.add(Project(code=normalized_code, name=normalized_name))
    db.commit()
    return build_redirect("/projects", message="Проект успешно создан.")


@router.post("/projects/{project_id}/update")
def update_project(
    project_id: int,
    code: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для обновления данных существующего проекта."""
    project = db.get(Project, project_id)
    if not project:
        return build_redirect("/projects", error="Проект не найден.")

    normalized_code = code.strip()
    normalized_name = name.strip()
    if not normalized_code or not normalized_name:
        return build_redirect("/projects", error="Нужно заполнить код и название проекта.")

    existing = (
        db.query(Project)
        .filter(
            ((Project.code == normalized_code) | (Project.name == normalized_name))
            & (Project.id != project_id)
        )
        .first()
    )
    if existing:
        return build_redirect("/projects", error="Проект с таким кодом или названием уже существует.")

    project.code = normalized_code
    project.name = normalized_name
    db.add(project)
    db.commit()
    return build_redirect("/projects", message="Проект успешно обновлен.")


@router.post("/projects/{project_id}/delete")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для удаления проекта из системы."""
    project = db.get(Project, project_id)
    if not project:
        return build_redirect("/projects", error="Проект не найден.")

    has_users = db.query(User).filter(User.project_id == project_id).first()
    has_profiles = db.query(LoadProfile).filter(LoadProfile.project_id == project_id).first()
    has_reports = db.query(Report).filter(Report.project_id == project_id).first()
    if has_users or has_profiles or has_reports:
        return build_redirect("/projects", error="Нельзя удалить проект, пока к нему привязаны пользователи, профили или отчеты.")

    db.delete(project)
    db.commit()
    return build_redirect("/projects", message="Проект удален.")


@router.get("/profiles")
def profiles_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Функция для отображения страницы профилей нагрузочного тестирования."""
    return templates.TemplateResponse(
        "profiles.html",
        {
            "request": request,
            "user": current_user,
            "profiles": get_profiles_query(db, current_user).all(),
            "projects": get_available_projects_for_user(db, current_user),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "role_labels": ROLE_LABELS,
        },
    )


@router.post("/profiles")
def create_profile(
    name: str = Form(...),
    project_id: str = Form(""),
    operation_name: list[str] = Form(...),
    operation_sla_ms: list[str] = Form(...),
    operation_executions_per_hour: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для создания нового профиля нагрузочного тестирования."""
    profile_name = name.strip()
    if not profile_name:
        return build_redirect("/profiles", error="Нужно указать название профиля НТ.")

    allowed_projects = {str(project.id): project for project in get_available_projects_for_user(db, current_user)}
    selected_project_id = project_id.strip()
    resolved_project_id = None

    if selected_project_id:
        selected_project = allowed_projects.get(selected_project_id)
        if not selected_project:
            return build_redirect("/profiles", error="Недопустимый проект для текущего пользователя.")
        resolved_project_id = selected_project.id

    rows = zip(operation_name, operation_sla_ms, operation_executions_per_hour)
    parsed_operations = []

    for raw_name, raw_sla, raw_exec in rows:
        op_name = raw_name.strip()
        sla_value = raw_sla.strip()
        exec_value = raw_exec.strip()

        if not op_name and not sla_value and not exec_value:
            continue

        if not op_name or not sla_value or not exec_value:
            return build_redirect("/profiles", error="Для каждой операции нужно заполнить название, SLA и количество в час.")

        try:
            sla_ms = float(sla_value.replace(",", "."))
            executions = int(exec_value)
        except ValueError:
            return build_redirect("/profiles", error="SLA должен быть числом, а количество операций в час - целым числом.")

        if sla_ms < 0 or executions < 0:
            return build_redirect("/profiles", error="SLA и количество операций в час не могут быть отрицательными.")

        parsed_operations.append(
            LoadProfileOperation(
                name=op_name,
                sla_ms=sla_ms,
                executions_per_hour=executions,
            )
        )

    if not parsed_operations:
        return build_redirect("/profiles", error="Добавь хотя бы одну операцию в профиль НТ.")

    profile = LoadProfile(name=profile_name, project_id=resolved_project_id, operations=parsed_operations)
    db.add(profile)
    db.commit()
    return build_redirect("/profiles", message="Профиль НТ успешно создан.")


@router.post("/profiles/{profile_id}/update")
def update_profile(
    profile_id: int,
    name: str = Form(...),
    project_id: str = Form(""),
    operation_name: list[str] = Form(...),
    operation_sla_ms: list[str] = Form(...),
    operation_executions_per_hour: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для обновления существующего профиля нагрузочного тестирования."""
    profile = db.get(LoadProfile, profile_id)
    if not profile:
        return build_redirect("/profiles", error="Профиль НТ не найден.")

    if current_user.role != "ADMIN":
        if current_user.project_id:
            if profile.project_id != current_user.project_id:
                return build_redirect("/profiles", error="Нет доступа к этому профилю.")
        elif profile.project_id is not None:
            return build_redirect("/profiles", error="Нет доступа к этому профилю.")

    profile_name = name.strip()
    if not profile_name:
        return build_redirect("/profiles", error="Нужно указать название профиля НТ.")

    allowed_projects = {str(project.id): project for project in get_available_projects_for_user(db, current_user)}
    selected_project_id = project_id.strip()
    resolved_project_id = None
    if selected_project_id:
        selected_project = allowed_projects.get(selected_project_id)
        if not selected_project:
            return build_redirect("/profiles", error="Недопустимый проект для текущего пользователя.")
        resolved_project_id = selected_project.id

    rows = zip(operation_name, operation_sla_ms, operation_executions_per_hour)
    parsed_operations = []
    for raw_name, raw_sla, raw_exec in rows:
        op_name = raw_name.strip()
        sla_value = raw_sla.strip()
        exec_value = raw_exec.strip()

        if not op_name and not sla_value and not exec_value:
            continue
        if not op_name or not sla_value or not exec_value:
            return build_redirect("/profiles", error="Для каждой операции нужно заполнить название, SLA и количество в час.")

        try:
            sla_ms = float(sla_value.replace(",", "."))
            executions = int(exec_value)
        except ValueError:
            return build_redirect("/profiles", error="SLA должен быть числом, а количество операций в час - целым числом.")

        if sla_ms < 0 or executions < 0:
            return build_redirect("/profiles", error="SLA и количество операций в час не могут быть отрицательными.")

        parsed_operations.append(
            LoadProfileOperation(
                name=op_name,
                sla_ms=sla_ms,
                executions_per_hour=executions,
            )
        )

    if not parsed_operations:
        return build_redirect("/profiles", error="Добавь хотя бы одну операцию в профиль НТ.")

    profile.name = profile_name
    profile.project_id = resolved_project_id
    profile.operations.clear()
    for operation in parsed_operations:
        profile.operations.append(operation)
    db.add(profile)
    db.commit()
    return build_redirect("/profiles", message="Профиль НТ обновлен.")


@router.post("/profiles/{profile_id}/delete")
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для удаления профиля нагрузочного тестирования."""
    profile = db.get(LoadProfile, profile_id)
    if not profile:
        return build_redirect("/profiles", error="Профиль НТ не найден.")

    if current_user.role != "ADMIN":
        if current_user.project_id:
            if profile.project_id != current_user.project_id:
                return build_redirect("/profiles", error="Нет доступа к этому профилю.")
        elif profile.project_id is not None:
            return build_redirect("/profiles", error="Нет доступа к этому профилю.")

    has_tests = db.query(TestRun).filter(TestRun.load_profile_id == profile_id).first()
    if has_tests:
        return build_redirect("/profiles", error="Нельзя удалить профиль НТ, пока по нему существуют тесты.")

    db.delete(profile)
    db.commit()
    return build_redirect("/profiles", message="Профиль НТ удален.")


@router.get("/tests")
def tests_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Функция для отображения страницы с тестовыми прогонами."""
    tests_query = db.query(TestRun)
    if current_user.role != "ADMIN":
        if current_user.project_id:
            tests_query = tests_query.join(TestRun.load_profile).filter(LoadProfile.project_id == current_user.project_id)
        else:
            tests_query = tests_query.join(TestRun.load_profile).filter(LoadProfile.project_id.is_(None))
    return templates.TemplateResponse(
        "tests.html",
        {
            "request": request,
            "user": current_user,
            "tests": tests_query.order_by(TestRun.created_at.desc()).all(),
            "profiles": get_available_profiles_for_user(db, current_user),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/tests")
def create_test(
    name: str = Form(...),
    load_profile_id: str = Form(...),
    started_at: str = Form(...),
    finished_at: str = Form(...),
    load_percent: str = Form(...),
    influx_bucket: str = Form(""),
    prometheus_url: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для создания нового тестового прогона."""
    payload, error = parse_test_form(
        db,
        current_user,
        name,
        load_profile_id,
        started_at,
        finished_at,
        load_percent,
        influx_bucket,
        prometheus_url,
    )
    if error:
        return build_redirect("/tests", error=error)

    db.add(TestRun(**payload))
    db.commit()
    return build_redirect("/tests", message="Тест успешно создан.")


@router.post("/tests/{test_id}/update")
def update_test(
    test_id: int,
    name: str = Form(...),
    load_profile_id: str = Form(...),
    started_at: str = Form(...),
    finished_at: str = Form(...),
    load_percent: str = Form(...),
    influx_bucket: str = Form(""),
    prometheus_url: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для обновления существующего тестового прогона."""
    test_run = db.get(TestRun, test_id)
    if not test_run:
        return build_redirect("/tests", error="Тест не найден.")
    if not user_can_access_test(current_user, test_run):
        return build_redirect("/tests", error="Нет доступа к этому тесту.")

    payload, error = parse_test_form(
        db,
        current_user,
        name,
        load_profile_id,
        started_at,
        finished_at,
        load_percent,
        influx_bucket,
        prometheus_url,
    )
    if error:
        return build_redirect("/tests", error=error)

    for field, value in payload.items():
        setattr(test_run, field, value)
    db.add(test_run)
    db.commit()
    return build_redirect("/tests", message="Тест обновлен.")


@router.post("/tests/{test_id}/delete")
def delete_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для удаления тестового прогона."""
    test_run = db.get(TestRun, test_id)
    if not test_run:
        return build_redirect("/tests", error="Тест не найден.")
    if not user_can_access_test(current_user, test_run):
        return build_redirect("/tests", error="Нет доступа к этому тесту.")

    has_reports = db.query(Report).filter((Report.test_run_id == test_id) | (Report.second_test_run_id == test_id)).first()
    if has_reports:
        return build_redirect("/tests", error="Нельзя удалить тест, пока по нему существуют отчеты.")

    db.delete(test_run)
    db.commit()
    return build_redirect("/tests", message="Тест удален.")


@router.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Функция для отображения страницы со списком отчетов."""
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "user": current_user,
            "reports": get_reports_query(db, current_user).all(),
            "tests": get_available_tests_for_user(db, current_user),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "report_type_target": REPORT_TYPE_TARGET,
            "report_type_comparative": REPORT_TYPE_COMPARATIVE,
        },
    )


@router.post("/reports")
def create_report(
    name: str = Form(...),
    report_type: str = Form(...),
    test_run_id: str = Form(...),
    second_test_run_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для создания нового отчета по одному или двум тестам."""
    normalized_name = name.strip()
    normalized_type = report_type.strip().upper()
    if not normalized_name:
        return build_redirect("/reports", error="Нужно указать название отчета.")
    if normalized_type not in {REPORT_TYPE_TARGET, REPORT_TYPE_COMPARATIVE}:
        return build_redirect("/reports", error="Выбран некорректный тип отчета.")

    try:
        first_test_id = int(test_run_id)
    except ValueError:
        return build_redirect("/reports", error="Нужно выбрать тест для отчета.")

    first_test = db.get(TestRun, first_test_id)
    if not first_test or not user_can_access_test(current_user, first_test):
        return build_redirect("/reports", error="Выбранный тест недоступен для текущего пользователя.")

    second_test = None
    if normalized_type == REPORT_TYPE_COMPARATIVE:
        if not second_test_run_id.strip():
            return build_redirect("/reports", error="Для сравнительного отчета нужно выбрать второй тест.")
        try:
            second_test_id_value = int(second_test_run_id)
        except ValueError:
            return build_redirect("/reports", error="Некорректно выбран второй тест.")

        second_test = db.get(TestRun, second_test_id_value)
        if not second_test or not user_can_access_test(current_user, second_test):
            return build_redirect("/reports", error="Второй тест недоступен для текущего пользователя.")
        if second_test.id == first_test.id:
            return build_redirect("/reports", error="Для сравнительного отчета нужно выбрать два разных теста.")
        if first_test.load_profile.project_id != second_test.load_profile.project_id:
            return build_redirect("/reports", error="Сравнивать можно только тесты одного проекта.")

    template_item = get_default_report_template(db, normalized_type)
    if not template_item:
        return build_redirect("/reports", error="Не найден системный шаблон для выбранного типа отчета.")

    project_id = first_test.load_profile.project_id
    if project_id is None:
        return build_redirect("/reports", error="У выбранного теста не задан проект.")

    report = Report(
        test_run_id=first_test.id,
        second_test_run_id=second_test.id if second_test else None,
        project_id=project_id,
        user_id=current_user.id,
        template_id=template_item.id,
        name=normalized_name,
        file_path="",
        report_type=normalized_type,
        status="ERROR",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    service = ReportService()
    try:
        context = (
            service.build_target_report_context(first_test)
            if normalized_type == REPORT_TYPE_TARGET
            else service.build_comparative_report_context(first_test, second_test)
        )
        context["author_login"] = current_user.login
        content = service.render_report(template_item, context)
        file_path = service.export_report_file(report, content)
    except Exception:
        report.status = "ERROR"
        db.add(report)
        db.commit()
        return build_redirect("/reports", error="Не удалось сформировать отчет.")

    report.file_path = service.to_storage_path(file_path)
    report.status = context.get("result", "READY") if normalized_type == REPORT_TYPE_TARGET else "COMPARATIVE"
    db.add(report)
    db.commit()

    return build_redirect("/reports", message="Отчет успешно сформирован и сохранен.")


@router.get("/reports/{report_id}/view")
def view_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Функция для открытия уже сформированного отчета."""
    report = db.get(Report, report_id)
    if not report:
        return build_redirect("/reports", error="Отчет не найден.")
    if not user_can_access_report(current_user, report):
        return build_redirect("/reports", error="Нет доступа к этому отчету.")

    report_path = ReportService().resolve_report_path(report.file_path)
    if not report_path.exists():
        return build_redirect("/reports", error="Файл отчета не найден на диске.")

    return FileResponse(path=report_path, filename=report_path.name, media_type="text/html")


@router.post("/reports/{report_id}/delete")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ENGINEER")),
):
    """Функция для удаления отчета и связанного файла с диска."""
    report = db.get(Report, report_id)
    if not report:
        return build_redirect("/reports", error="Отчет не найден.")
    if not user_can_access_report(current_user, report):
        return build_redirect("/reports", error="Нет доступа к этому отчету.")

    report_path = ReportService().resolve_report_path(report.file_path) if report.file_path else None
    db.delete(report)
    db.commit()

    if report_path and report_path.exists():
        report_path.unlink()

    return build_redirect("/reports", message="Отчет удален.")


@router.get("/report-templates")
def report_templates_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """Функция для отображения страницы с шаблонами отчетов."""
    return templates.TemplateResponse(
        "report_templates.html",
        {
            "request": request,
            "user": current_user,
            "templates_list": db.query(ReportTemplate).order_by(ReportTemplate.name).all(),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/report-templates")
async def upload_report_template(
    name: str = Form(...),
    template_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для загрузки нового HTML-шаблона отчета в систему."""
    normalized_name = name.strip()
    if not normalized_name:
        return build_redirect("/report-templates", error="Нужно указать название шаблона.")

    existing = db.query(ReportTemplate).filter(ReportTemplate.name == normalized_name).first()
    if existing:
        return build_redirect("/report-templates", error="Шаблон с таким названием уже существует.")

    extension = Path(template_file.filename or "").suffix.lower()
    if extension not in {".html", ".htm"}:
        return build_redirect("/report-templates", error="Можно загружать только HTML-файлы.")

    ensure_template_storage_dir()
    target_path = TEMPLATE_STORAGE_DIR / f"{uuid4().hex}{extension}"

    content = await template_file.read()
    target_path.write_bytes(content)

    db.add(ReportTemplate(name=normalized_name, file_path=to_storage_path(target_path)))
    db.commit()
    return build_redirect("/report-templates", message="Шаблон успешно загружен.")


@router.get("/report-templates/{template_id}/download")
def download_report_template(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для скачивания выбранного шаблона отчета."""
    template_item = db.get(ReportTemplate, template_id)
    if not template_item:
        return build_redirect("/report-templates", error="Шаблон не найден.")

    template_path = resolve_storage_path(template_item.file_path)
    if not template_path.exists():
        return build_redirect("/report-templates", error="Файл шаблона не найден на диске.")

    return FileResponse(path=template_path, filename=template_path.name, media_type="text/html")


@router.post("/report-templates/{template_id}/delete")
def delete_report_template(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для удаления шаблона отчета из системы."""
    template_item = db.get(ReportTemplate, template_id)
    if not template_item:
        return build_redirect("/report-templates", error="Шаблон не найден.")

    in_use = db.query(Report).filter(Report.template_id == template_id).first()
    if in_use:
        return build_redirect("/report-templates", error="Нельзя удалить шаблон, который уже используется в отчетах.")

    template_path = resolve_storage_path(template_item.file_path)
    db.delete(template_item)
    db.commit()

    if template_path.exists():
        template_path.unlink()

    return build_redirect("/report-templates", message="Шаблон удален.")


@router.get("/users")
def users_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("ADMIN")),
):
    """Функция для отображения страницы управления пользователями."""
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "user": current_user,
            "users": db.query(User).order_by(User.created_at.desc()).all(),
            "projects": db.query(Project).order_by(Project.name).all(),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "role_labels": ROLE_LABELS,
        },
    )


@router.post("/users")
def create_user(
    login: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    project_id: str = Form(""),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для создания нового пользователя."""
    normalized_login = login.strip()
    normalized_email = email.strip()
    normalized_role = role.strip().upper()
    resolved_project_id = int(project_id) if project_id.strip() else None

    if normalized_role not in ROLE_LABELS:
        return build_redirect("/users", error="Выбрана некорректная роль.")

    if not normalized_login or not normalized_email or not password.strip():
        return build_redirect("/users", error="Нужно заполнить логин, почту и пароль.")

    existing_user = db.query(User).filter((User.login == normalized_login) | (User.email == normalized_email)).first()
    if existing_user:
        return build_redirect("/users", error="Пользователь с таким логином или почтой уже существует.")

    if resolved_project_id is not None and not db.get(Project, resolved_project_id):
        return build_redirect("/users", error="Выбранный проект не найден.")

    db.add(
        User(
            login=normalized_login,
            email=normalized_email,
            password_hash=get_password_hash(password),
            role=normalized_role,
            project_id=resolved_project_id,
        )
    )
    db.commit()
    return build_redirect("/users", message="Пользователь успешно создан.")


@router.post("/users/{user_id}/update")
def update_user(
    user_id: int,
    login: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    role: str = Form(...),
    project_id: str = Form(""),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_role("ADMIN")),
):
    """Функция для обновления основных данных пользователя."""
    user = db.get(User, user_id)
    if not user:
        return build_redirect("/users", error="Пользователь не найден.")

    normalized_login = login.strip()
    normalized_email = email.strip()
    normalized_role = role.strip().upper()
    resolved_project_id = int(project_id) if project_id.strip() else None

    if normalized_role not in ROLE_LABELS:
        return build_redirect("/users", error="Выбрана некорректная роль.")
    if not normalized_login or not normalized_email:
        return build_redirect("/users", error="Нужно заполнить логин и почту.")
    if resolved_project_id is not None and not db.get(Project, resolved_project_id):
        return build_redirect("/users", error="Выбранный проект не найден.")

    existing_user = (
        db.query(User)
        .filter(((User.login == normalized_login) | (User.email == normalized_email)) & (User.id != user_id))
        .first()
    )
    if existing_user:
        return build_redirect("/users", error="Пользователь с таким логином или почтой уже существует.")

    user.login = normalized_login
    user.email = normalized_email
    user.role = normalized_role
    user.project_id = resolved_project_id
    if password.strip():
        user.password_hash = get_password_hash(password)

    if current_admin.id == user.id and user.role != "ADMIN":
        return build_redirect("/users", error="Нельзя снять роль администратора с текущей учетной записи.")

    db.add(user)
    db.commit()
    return build_redirect("/users", message="Пользователь обновлен.")


@router.post("/users/{user_id}/assignment")
def update_user_assignment(
    user_id: int,
    role: str = Form(...),
    project_id: str = Form(""),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """Функция для обновления роли и проектной привязки пользователя."""
    user = db.get(User, user_id)
    if not user:
        return build_redirect("/users", error="Пользователь не найден.")

    normalized_role = role.strip().upper()
    if normalized_role not in ROLE_LABELS:
        return build_redirect("/users", error="Выбрана некорректная роль.")

    resolved_project_id = int(project_id) if project_id.strip() else None
    if resolved_project_id is not None and not db.get(Project, resolved_project_id):
        return build_redirect("/users", error="Выбранный проект не найден.")

    user.role = normalized_role
    user.project_id = resolved_project_id
    db.add(user)
    db.commit()
    return build_redirect("/users", message="Привязка пользователя обновлена.")


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_role("ADMIN")),
):
    """Функция для удаления пользователя из системы."""
    user = db.get(User, user_id)
    if not user:
        return build_redirect("/users", error="Пользователь не найден.")
    if current_admin.id == user.id:
        return build_redirect("/users", error="Нельзя удалить текущую учетную запись администратора.")

    has_reports = db.query(Report).filter(Report.user_id == user_id).first()
    if has_reports:
        return build_redirect("/users", error="Нельзя удалить пользователя, пока за ним закреплены отчеты.")

    db.delete(user)
    db.commit()
    return build_redirect("/users", message="Пользователь удален.")
