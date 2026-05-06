import unittest
from datetime import datetime

from app.api.views.pages import parse_datetime_value


class PagesHelpersTests(unittest.TestCase):
    def test_parse_datetime_value_supports_grafana_format(self) -> None:
        value = "2026-04-25 20:18:41"

        result = parse_datetime_value(value)

        self.assertEqual(datetime(2026, 4, 25, 20, 18, 41), result)

    def test_parse_datetime_value_supports_html_datetime_local_format(self) -> None:
        value = "2026-04-25T20:18"

        result = parse_datetime_value(value)

        self.assertEqual(datetime(2026, 4, 25, 20, 18), result)

    def test_parse_datetime_value_raises_value_error_for_empty_string(self) -> None:
        with self.assertRaises(ValueError):
            parse_datetime_value("")


if __name__ == "__main__":
    unittest.main()
