import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.services.dashboard_service import _get_available_project_ids, _normalize_day


class DashboardServiceTests(unittest.TestCase):
    def test_get_available_project_ids_returns_empty_list_for_admin(self) -> None:
        user = SimpleNamespace(role="ADMIN", project_id=7)

        result = _get_available_project_ids(user)

        self.assertEqual([], result)

    def test_get_available_project_ids_returns_user_project_for_non_admin(self) -> None:
        user = SimpleNamespace(role="ENGINEER", project_id=7)

        result = _get_available_project_ids(user)

        self.assertEqual([7], result)

    def test_get_available_project_ids_returns_empty_list_when_project_is_missing(self) -> None:
        user = SimpleNamespace(role="CUSTOMER", project_id=None)

        result = _get_available_project_ids(user)

        self.assertEqual([], result)

    def test_normalize_day_keeps_date_value(self) -> None:
        value = date(2026, 5, 6)

        result = _normalize_day(value)

        self.assertEqual(value, result)

    def test_normalize_day_converts_datetime_to_date(self) -> None:
        value = datetime(2026, 5, 6, 12, 30, 0)

        result = _normalize_day(value)

        self.assertEqual(date(2026, 5, 6), result)


if __name__ == "__main__":
    unittest.main()
