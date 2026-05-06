import unittest
from datetime import timedelta

from app.services.report_service import ReportService


class ReportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ReportService()

    def test_format_duration_returns_hh_mm_ss(self) -> None:
        result = self.service._format_duration(timedelta(hours=1, minutes=2, seconds=3))

        self.assertEqual("01:02:03", result)

    def test_hardware_breach_is_true_when_value_is_above_threshold(self) -> None:
        self.assertTrue(self.service._is_hardware_breach(81.0))

    def test_hardware_breach_is_false_when_value_is_within_threshold(self) -> None:
        self.assertFalse(self.service._is_hardware_breach(80.0))

    def test_profile_hit_class_returns_red_when_out_of_allowed_range(self) -> None:
        self.assertEqual("tone-red", self.service._profile_hit_class(110.0))

    def test_profile_hit_label_returns_boundary_branch_label(self) -> None:
        near_boundary_label = self.service._profile_hit_label(103.0)

        self.assertEqual(near_boundary_label, self.service._profile_hit_label(97.0))
        self.assertNotEqual(near_boundary_label, self.service._profile_hit_label(100.0))
        self.assertNotEqual(near_boundary_label, self.service._profile_hit_label(110.0))

    def test_build_change_marker_returns_good_for_lower_response_time(self) -> None:
        result = self.service._build_change_marker(2.0, 1.0, better_when="lower")

        self.assertEqual("change-good", result["class"])
        self.assertEqual("↑", result["symbol"])

    def test_build_profile_change_marker_returns_good_when_second_value_is_closer_to_100(self) -> None:
        result = self.service._build_profile_change_marker(90.0, 98.0)

        self.assertEqual("change-good", result["class"])
        self.assertEqual("↑", result["symbol"])

    def test_build_boolean_summary_row_marks_worse_when_problem_appears_in_second_test(self) -> None:
        result = self.service._build_boolean_summary_row("Ошибки", False, True)

        self.assertEqual("Да", result["second_value"])
        self.assertEqual("change-bad", result["change"]["class"])

    def test_build_tone_class_returns_yellow_when_response_is_close_to_threshold(self) -> None:
        result = self.service._build_tone_class("PASS", 2.0, 1.7)

        self.assertEqual("tone-yellow", result)

    def test_build_change_marker_returns_neutral_for_equal_values(self) -> None:
        result = self.service._build_change_marker(5.0, 5.0, better_when="lower")

        self.assertEqual("change-neutral", result["class"])
        self.assertEqual("=", result["symbol"])

    def test_ms_to_seconds_converts_value(self) -> None:
        self.assertEqual(1.5, self.service._ms_to_seconds(1500.0))


if __name__ == "__main__":
    unittest.main()
