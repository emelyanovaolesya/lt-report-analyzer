from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import LoadProfile, Project, Report, TestRun, User


def build_dashboard_context(session: Session, current_user: User) -> dict:
    """Функция для сборки данных, которые нужны для главной страницы."""
    project_ids = _get_available_project_ids(current_user)
    stats = _build_stats(session, current_user, project_ids)
    recent_tests = _get_recent_tests(session, current_user, project_ids)
    recent_reports = _get_recent_reports(session, current_user, project_ids)
    trend = _build_activity_trend(session, current_user, project_ids)
    quality = _build_month_quality(session, current_user, project_ids)

    return {
        "stats": stats,
        "recent_tests": recent_tests,
        "recent_reports": recent_reports,
        "activity_trend": trend,
        "month_quality": quality,
    }


def _get_available_project_ids(current_user: User) -> list[int]:
    """Функция для определения списка проектов, доступных текущему пользователю."""
    if current_user.role == "ADMIN":
        return []
    return [current_user.project_id] if current_user.project_id else []


def _build_stats(session: Session, current_user: User, project_ids: list[int]) -> dict:
    """Функция для расчета основных карточек со статистикой на главной странице."""
    if current_user.role == "ADMIN":
        return {
            "projects": session.query(Project).count(),
            "users": session.query(User).count(),
            "profiles": session.query(LoadProfile).count(),
            "tests": session.query(TestRun).count(),
            "reports": session.query(Report).count(),
        }

    project_count = len(project_ids)
    profile_count = _filter_profiles(session, project_ids).count()
    test_count = _filter_tests(session, project_ids).count()
    report_count = _filter_reports(session, current_user, project_ids).count()

    return {
        "projects": project_count,
        "profiles": profile_count,
        "tests": test_count,
        "reports": report_count,
    }


def _get_recent_tests(session: Session, current_user: User, project_ids: list[int]) -> list[TestRun]:
    """Функция для получения последних тестов, доступных текущему пользователю."""
    query = _filter_tests(session, project_ids).order_by(TestRun.created_at.desc())
    return query.limit(5).all()


def _get_recent_reports(session: Session, current_user: User, project_ids: list[int]) -> list[Report]:
    """Функция для получения последних отчетов, которые пользователь может открыть."""
    query = _filter_reports(session, current_user, project_ids).order_by(Report.created_at.desc())
    return query.limit(5).all()


def _build_activity_trend(session: Session, current_user: User, project_ids: list[int]) -> dict:
    """Функция для подготовки данных графика активности по тестам и отчетам."""
    if current_user.role == "ADMIN":
        return {"labels": [], "tests": [], "reports": [], "max_value": 0}

    today = date.today()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    labels = [item.strftime("%d.%m") for item in days]

    tests_rows = (
        _filter_tests(session, project_ids)
        .with_entities(func.date(TestRun.created_at).label("day"), func.count(TestRun.id))
        .filter(TestRun.created_at >= days[0])
        .group_by(func.date(TestRun.created_at))
        .all()
    )
    reports_rows = (
        _filter_reports(session, current_user, project_ids)
        .with_entities(func.date(Report.created_at).label("day"), func.count(Report.id))
        .filter(Report.created_at >= days[0])
        .group_by(func.date(Report.created_at))
        .all()
    )

    tests_map = {_normalize_day(day): count for day, count in tests_rows}
    reports_map = {_normalize_day(day): count for day, count in reports_rows}

    tests_values = [int(tests_map.get(item, 0)) for item in days]
    reports_values = [int(reports_map.get(item, 0)) for item in days]
    max_value = max(tests_values + reports_values + [1])
    points = []
    for label, tests_value, reports_value in zip(labels, tests_values, reports_values):
        points.append(
            {
                "label": label,
                "tests": tests_value,
                "reports": reports_value,
                "tests_height": max(12, round((tests_value / max_value) * 120)) if tests_value > 0 else 12,
                "reports_height": max(12, round((reports_value / max_value) * 120)) if reports_value > 0 else 12,
            }
        )

    return {
        "labels": labels,
        "tests": tests_values,
        "reports": reports_values,
        "max_value": max_value,
        "points": points,
    }


def _build_month_quality(session: Session, current_user: User, project_ids: list[int]) -> dict:
    """Функция для расчета успешных и неуспешных тестов за последний месяц."""
    period_start = date.today() - timedelta(days=30)
    query = _filter_reports(session, current_user, project_ids).filter(
        Report.report_type == "TARGET",
        Report.created_at >= period_start,
    )

    successful = query.filter(Report.status == "PASS").count()
    unsuccessful = query.filter(Report.status == "FAIL").count()

    return {
        "successful": successful,
        "unsuccessful": unsuccessful,
        "period_label": "за последний месяц",
    }


def _normalize_day(value) -> date:
    """Функция для приведения значения даты к единому формату."""
    if isinstance(value, date):
        return value
    return value.date()


def _filter_profiles(session: Session, project_ids: list[int]):
    """Функция для фильтрации профилей по доступным проектам."""
    query = session.query(LoadProfile)
    if project_ids:
        query = query.filter(LoadProfile.project_id.in_(project_ids))
    else:
        query = query.filter(LoadProfile.project_id.is_(None))
    return query


def _filter_tests(session: Session, project_ids: list[int]):
    """Функция для фильтрации тестов по доступным проектам."""
    query = session.query(TestRun).join(TestRun.load_profile)
    if project_ids:
        query = query.filter(LoadProfile.project_id.in_(project_ids))
    else:
        query = query.filter(LoadProfile.project_id.is_(None))
    return query


def _filter_reports(session: Session, current_user: User, project_ids: list[int]):
    """Функция для фильтрации отчетов с учетом роли и проектных ограничений."""
    query = session.query(Report)
    if current_user.role == "ADMIN":
        return query
    if project_ids:
        return query.filter(Report.project_id.in_(project_ids))
    return query.filter(Report.user_id == current_user.id)
