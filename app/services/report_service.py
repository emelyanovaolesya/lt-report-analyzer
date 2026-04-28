from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from jinja2 import Template

from app.core.config import settings
from app.models import Report, ReportTemplate, TestRun
from app.services.grafana_service import GrafanaService
from app.services.metrics_service import MetricsService
from app.services.template_storage import resolve_storage_path


class ReportService:
    """Главный сервис, где собирается логика анализа тестов и формирования отчетов."""
    RESOURCE_THRESHOLD_PERCENT = 80.0

    def __init__(self) -> None:
        """Подключает вспомогательные сервисы, которые нужны для генерации отчета."""
        self.metrics_service = MetricsService()
        self.grafana_service = GrafanaService()

    def build_target_report_context(self, test_run: TestRun) -> dict:
        """Готовит все данные для целевого отчета по одному тесту."""
        analysis = self._analyze_test_run(test_run, include_graphs=True)

        if not analysis["issues"]:
            analysis["issues"].append(
                "Во время теста критических ошибок не обнаружено, запас производительности на текущем уровне нагрузки обеспечен."
            )

        if any(image is None for image in analysis["graphs"].values()):
            analysis["issues"].append("Часть графиков из Grafana не удалось встроить в отчет автоматически.")

        return {
            "test_name": test_run.name,
            "started_at": self._format_datetime(test_run.started_at),
            "finished_at": self._format_datetime(test_run.finished_at),
            "hold_duration": self._format_duration(test_run.finished_at - test_run.started_at),
            "load_percent": test_run.load_percent,
            "result": analysis["result"],
            "critical_errors": analysis["critical_errors_text"],
            "issues": analysis["issues"],
            "response_summary": analysis["response_summary"],
            "profile_hits": analysis["profile_hits"],
            "transaction_overview": analysis["transaction_overview"],
            "cpu_usage": self._format_percent(analysis["hardware_map"]["CPU"]),
            "ram_usage": self._format_percent(analysis["hardware_map"]["RAM"]),
            "disk_usage": self._format_percent(analysis["hardware_map"]["DISK"]),
            "hardware_findings": analysis["hardware_findings"],
            "error_percent": f"{analysis['error_percent']:.2f}%",
            "error_count_total": analysis["error_count_total"],
            "error_highlight_class": "metric-danger" if analysis["error_count_total"] > 0 else "",
            "total_requests": analysis["total_requests"],
            "max_threads": analysis["max_threads"],
            "throughput_peak_rps": f"{analysis['throughput_peak_rps']:.2f} req/s",
            "graphs": analysis["graphs"],
            "grafana_link": analysis["grafana_link"],
            "result_class": "result-pass" if analysis["result"] == "PASS" else "result-fail",
            "result_label": "Успешно" if analysis["result"] == "PASS" else "Провален",
        }

    def build_comparative_report_context(self, first_test: TestRun, second_test: TestRun) -> dict:
        """Готовит данные для сравнительного отчета по двум тестовым прогонам."""
        first = self._analyze_test_run(first_test, include_graphs=False)
        second = self._analyze_test_run(second_test, include_graphs=False)

        first_flags = {
            "errors": first["has_errors"],
            "sla": first["has_sla_breach"],
            "profile": first["has_profile_miss"],
            "hardware": first["has_hardware_breach"],
        }
        second_flags = {
            "errors": second["has_errors"],
            "sla": second["has_sla_breach"],
            "profile": second["has_profile_miss"],
            "hardware": second["has_hardware_breach"],
        }

        degrade = any(not first_flags[key] and second_flags[key] for key in first_flags)
        improve = any(first_flags[key] and not second_flags[key] for key in first_flags)

        if degrade:
            verdict = {
                "title": "Замечена деградация",
                "class": "verdict-bad",
            }
        elif improve:
            verdict = {
                "title": "Замечено улучшение",
                "class": "verdict-good",
            }
        else:
            verdict = {
                "title": "Изменения не зафиксированы",
                "class": "verdict-neutral",
            }

        summary_rows = [
            self._build_boolean_summary_row("Ошибки", first_flags["errors"], second_flags["errors"]),
            self._build_boolean_summary_row("Превышения SLA", first_flags["sla"], second_flags["sla"]),
            self._build_boolean_summary_row("Непопадания в профиль", first_flags["profile"], second_flags["profile"]),
            self._build_boolean_summary_row(
                "Превышения утилизации аппаратных ресурсов",
                first_flags["hardware"],
                second_flags["hardware"],
            ),
        ]

        first_operations = {item["name"]: item for item in first["operation_details"]}
        second_operations = {item["name"]: item for item in second["operation_details"]}
        operation_names = [operation.name for operation in first_test.load_profile.operations]

        response_rows = []
        profile_rows = []
        error_rows = []
        for operation_name in operation_names:
            first_item = first_operations.get(operation_name, {})
            second_item = second_operations.get(operation_name, {})

            first_response = first_item.get("actual_seconds")
            second_response = second_item.get("actual_seconds")
            response_rows.append(
                {
                    "operation_name": operation_name,
                    "first_value": self._format_seconds(first_response),
                    "second_value": self._format_seconds(second_response),
                    "change": self._build_change_marker(first_response, second_response, better_when="lower"),
                }
            )

            first_hit = first_item.get("profile_hit_percent")
            second_hit = second_item.get("profile_hit_percent")
            profile_rows.append(
                {
                    "operation_name": operation_name,
                    "first_value": self._format_hit_percent(first_hit),
                    "second_value": self._format_hit_percent(second_hit),
                    "change": self._build_profile_change_marker(first_hit, second_hit),
                }
            )

            first_errors = int(first_item.get("errors", 0) or 0)
            second_errors = int(second_item.get("errors", 0) or 0)
            error_rows.append(
                {
                    "operation_name": operation_name,
                    "first_value": first_errors,
                    "second_value": second_errors,
                    "first_class": "text-danger" if first_errors > 0 else "",
                    "second_class": "text-danger" if second_errors > 0 else "",
                }
            )

        hardware_rows = []
        for metric_name in ("CPU", "RAM", "DISK"):
            first_value = first["hardware_map"].get(metric_name)
            second_value = second["hardware_map"].get(metric_name)
            hardware_rows.append(
                {
                    "metric_name": metric_name,
                    "first_value": self._format_percent(first_value),
                    "second_value": self._format_percent(second_value),
                    "first_class": "text-danger" if self._is_hardware_breach(first_value) else "",
                    "second_class": "text-danger" if self._is_hardware_breach(second_value) else "",
                    "change": self._build_change_marker(first_value, second_value, better_when="lower"),
                }
            )

        return {
            "test_1": {
                "name": first_test.name,
                "time": self._format_duration(first_test.finished_at - first_test.started_at),
                "performance": f"{first_test.load_percent}%",
                "errors": first["error_count_total"],
                "grafana_link": first["grafana_link"],
            },
            "test_2": {
                "name": second_test.name,
                "time": self._format_duration(second_test.finished_at - second_test.started_at),
                "performance": f"{second_test.load_percent}%",
                "errors": second["error_count_total"],
                "grafana_link": second["grafana_link"],
            },
            "verdict": verdict,
            "comparison": {
                "summary_rows": summary_rows,
                "response_rows": response_rows,
                "profile_rows": profile_rows,
                "error_rows": error_rows,
                "hardware_rows": hardware_rows,
            },
        }

    def render_report(self, template_item: ReportTemplate, context: dict) -> str:
        """Функция для рендера HTML-отчета по шаблону и подготовленным данным."""
        template_path = resolve_storage_path(template_item.file_path)
        template = Template(template_path.read_text(encoding="utf-8"))
        return template.render(**context)

    def export_report_file(self, report: Report, content: str) -> Path:
        """Функция для сохранения готового отчета в HTML-файл."""
        output_dir = Path("generated_reports")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"report_{report.id}.html"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def to_storage_path(self, path: Path) -> str:
        """Функция для преобразования пути отчета в формат хранения."""
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()

    def resolve_report_path(self, file_path: str) -> Path:
        """Функция для получения полного пути к файлу отчета."""
        candidate = Path(file_path)
        if candidate.is_absolute():
            return candidate
        return Path.cwd() / candidate

    def _analyze_test_run(self, test_run: TestRun, include_graphs: bool) -> dict:
        """Функция для полного анализа теста перед формированием отчета."""
        business_metrics = self.metrics_service.fetch_influx_business_metrics(test_run)
        system_metrics = self.metrics_service.fetch_prometheus_system_metrics(test_run)
        start_utc, stop_utc = self.metrics_service.get_test_window_utc(test_run)
        graph_images = self.grafana_service.render_report_panels(start_utc, stop_utc) if include_graphs else {}

        response_summary: list[dict] = []
        profile_hits: list[dict] = []
        transaction_overview: list[dict] = []
        operation_details: list[dict] = []
        issues: list[str] = []
        critical_error_types: list[str] = []

        has_sla_breach = False
        has_operation_errors = False
        has_profile_miss = False

        operation_metrics_map = business_metrics["operation_metrics"]
        for operation in test_run.load_profile.operations:
            metrics = operation_metrics_map.get(operation.name, {})
            actual_seconds = self._ms_to_seconds(metrics.get("p95_max_ms"))
            sla_seconds = float(operation.sla_ms)
            error_count = int(metrics.get("errors", 0) or 0)
            actual_count = int(metrics.get("count_total", 0) or 0)
            slowest_request_seconds = self._ms_to_seconds(metrics.get("slowest_request_ms"))
            expected_count = int(operation.executions_per_hour)
            profile_hit_percent = (actual_count / expected_count * 100.0) if expected_count else None
            hit_class = self._profile_hit_class(profile_hit_percent)

            status = "PASS"
            if actual_seconds is None or actual_count == 0:
                status = "NO DATA"
                issues.append(f"По операции '{operation.name}' не удалось получить метрики из InfluxDB.")

            if actual_seconds is not None and actual_seconds > sla_seconds:
                status = "FAIL"
                has_sla_breach = True
                issues.append(self._format_sla_issue(operation.name, actual_seconds, sla_seconds))

            if error_count > 0:
                status = "FAIL"
                has_operation_errors = True
                issues.append(
                    f"В операции '{operation.name}' было зафиксировано "
                    f"<strong class=\"text-danger\">{error_count}</strong> ошибок."
                )

            if hit_class == "tone-red":
                has_profile_miss = True
                issues.append(self._format_profile_issue(operation.name, profile_hit_percent))

            response_summary.append(
                {
                    "name": operation.name,
                    "sla": self._format_seconds(sla_seconds),
                    "actual": self._format_seconds(actual_seconds),
                    "status": status,
                    "tone_class": self._build_tone_class(status, sla_seconds, actual_seconds),
                    "tone_label": self._build_tone_label(status, sla_seconds, actual_seconds),
                    "slowest_request_name": metrics.get("slowest_request_name") or "n/a",
                    "slowest_request_value": self._format_seconds(slowest_request_seconds),
                }
            )

            profile_hits.append(
                {
                    "name": operation.name,
                    "profile_count": expected_count,
                    "actual_count": actual_count,
                    "hit_percent": self._format_hit_percent(profile_hit_percent),
                    "hit_width": min(max(profile_hit_percent or 0.0, 0.0), 100.0),
                    "hit_class": hit_class,
                    "hit_label": self._profile_hit_label(profile_hit_percent),
                }
            )

            operation_details.append(
                {
                    "name": operation.name,
                    "actual_seconds": actual_seconds,
                    "sla_seconds": sla_seconds,
                    "errors": error_count,
                    "actual_count": actual_count,
                    "profile_count": expected_count,
                    "profile_hit_percent": profile_hit_percent,
                }
            )

        for item in sorted(
            business_metrics["transaction_metrics"],
            key=lambda row: row.get("transaction_name") or "",
        ):
            p95_seconds = self._ms_to_seconds(item.get("p95_max_ms"))
            transaction_overview.append(
                {
                    "transaction_name": item.get("transaction_name") or "n/a",
                    "response_time": self._format_seconds(p95_seconds),
                    "count_total": int(item.get("count_total", 0) or 0),
                    "errors": int(item.get("errors", 0) or 0),
                }
            )

        error_percent = float(business_metrics["error_percent"])
        error_count_total = int(business_metrics["error_count"])
        total_requests = int(business_metrics["total_requests"])
        max_threads = int(business_metrics["max_threads"])
        throughput_peak_rps = float(business_metrics["throughput_peak_rps"])

        hardware_map = {
            "CPU": system_metrics["cpu_usage_max"],
            "RAM": system_metrics["ram_usage_max"],
            "DISK": system_metrics["disk_usage_max"],
        }
        hardware_findings = [self._build_hardware_item(name, value) for name, value in hardware_map.items()]
        has_hardware_breach = any(item["breach"] for item in hardware_findings)

        if has_sla_breach:
            critical_error_types.append("Превышение SLA")
        if has_hardware_breach:
            critical_error_types.append("Превышение по утилизации аппаратных метрик")
        if has_profile_miss:
            critical_error_types.append("Непопадание в профиль")
        if has_operation_errors or error_count_total > 0:
            critical_error_types.append("Ошибки в операциях")

        for finding in hardware_findings:
            if finding["breach"]:
                issues.append(
                    f"{finding['title']} превысила допустимый порог: "
                    f"<strong class=\"text-danger\">{finding['value']}</strong> "
                    f"при пороге {finding['threshold']}."
                )

        result = "PASS"
        if has_sla_breach or has_hardware_breach or has_profile_miss or error_count_total > 0:
            result = "FAIL"

        return {
            "result": result,
            "critical_errors": critical_error_types,
            "critical_errors_text": ", ".join(critical_error_types) if critical_error_types else "Нет",
            "issues": issues,
            "response_summary": response_summary,
            "profile_hits": profile_hits,
            "transaction_overview": transaction_overview,
            "operation_details": operation_details,
            "hardware_map": hardware_map,
            "hardware_findings": hardware_findings,
            "error_percent": error_percent,
            "error_count_total": error_count_total,
            "total_requests": total_requests,
            "max_threads": max_threads,
            "throughput_peak_rps": throughput_peak_rps,
            "graphs": graph_images,
            "grafana_link": self._build_grafana_link(start_utc, stop_utc),
            "has_sla_breach": has_sla_breach,
            "has_errors": has_operation_errors or error_count_total > 0,
            "has_profile_miss": has_profile_miss,
            "has_hardware_breach": has_hardware_breach,
        }

    def _format_datetime(self, value) -> str:
        """Функция для форматирования даты и времени для отчета."""
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _format_duration(self, value: timedelta) -> str:
        """Функция для перевода длительности теста в удобный текстовый вид."""
        total_seconds = int(value.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _format_percent(self, value: float | None) -> str:
        """Функция для форматирования процентного значения."""
        if value is None:
            return "n/a"
        return f"{value:.2f}%"

    def _format_seconds(self, value: float | None) -> str:
        """Функция для форматирования времени отклика в секундах."""
        if value is None:
            return "n/a"
        return f"{value:.2f} сек"

    def _format_hit_percent(self, value: float | None) -> str:
        """Функция для форматирования процента попадания в профиль."""
        if value is None:
            return "n/a"
        return f"{value:.2f}%"

    def _build_grafana_link(self, start_utc, stop_utc) -> str:
        """Функция для формирования ссылки на Grafana по времени теста."""
        from_ms = int(start_utc.timestamp() * 1000)
        to_ms = int(stop_utc.timestamp() * 1000)
        return f"{settings.grafana_public_url}/d/{settings.grafana_dashboard_uid}?orgId=1&from={from_ms}&to={to_ms}"

    def _format_sla_issue(self, operation_name: str, actual_seconds: float, threshold_seconds: float) -> str:
        """Функция для текстового описания превышения SLA по операции."""
        return (
            f"Операция '{operation_name}' превысила SLA: "
            f"<strong class=\"text-danger\">{actual_seconds:.2f} сек</strong> "
            f"при пороге {threshold_seconds:.2f} сек."
        )

    def _format_profile_issue(self, operation_name: str, hit_percent: float | None) -> str:
        """Функция для текстового описания отклонения от профиля по операции."""
        value = 0.0 if hit_percent is None else hit_percent
        return (
            f'Отклонение от профиля по операции "{operation_name}": '
            f'<strong class="text-danger">{value:.2f}%</strong>.'
        )

    def _build_hardware_item(self, title: str, value: float | None) -> dict:
        """Функция для подготовки карточки аппаратной метрики."""
        breach = self._is_hardware_breach(value)
        return {
            "title": title,
            "value": self._format_percent(value),
            "threshold": f"{self.RESOURCE_THRESHOLD_PERCENT:.0f}%",
            "breach": breach,
            "card_class": "metric-danger" if breach else "",
        }

    def _is_hardware_breach(self, value: float | None) -> bool:
        """Функция для проверки превышения порога аппаратной метрики."""
        return value is not None and value > self.RESOURCE_THRESHOLD_PERCENT

    def _build_tone_class(self, status: str, sla_seconds: float, actual_seconds: float | None) -> str:
        """Функция для выбора CSS-класса по результату анализа операции."""
        if status == "FAIL":
            return "tone-red"
        if status == "NO DATA" or actual_seconds is None:
            return "tone-gray"
        if sla_seconds - actual_seconds <= 0.5:
            return "tone-yellow"
        return "tone-green"

    def _build_tone_label(self, status: str, sla_seconds: float, actual_seconds: float | None) -> str:
        """Функция для выбора текстовой метки по результату анализа операции."""
        if status == "FAIL":
            return "Превышен SLA"
        if status == "NO DATA" or actual_seconds is None:
            return "Нет данных"
        if sla_seconds - actual_seconds <= 0.5:
            return "Близко к порогу"
        return "Комфортный запас"

    def _profile_hit_class(self, hit_percent: float | None) -> str:
        """Функция для выбора CSS-класса по проценту попадания в профиль."""
        if hit_percent is None:
            return "tone-gray"
        if hit_percent < 95.0 or hit_percent > 105.0:
            return "tone-red"
        if hit_percent <= 97.0 or hit_percent >= 103.0:
            return "tone-yellow"
        return "tone-green"

    def _profile_hit_label(self, hit_percent: float | None) -> str:
        """Функция для выбора текстовой метки по проценту попадания в профиль."""
        if hit_percent is None:
            return "Нет данных"
        if hit_percent < 95.0 or hit_percent > 105.0:
            return "Вне допуска"
        if hit_percent <= 97.0 or hit_percent >= 103.0:
            return "Близко к границе"
        return "Допустимо"

    def _build_boolean_summary_row(self, label: str, first_value: bool, second_value: bool) -> dict:
        """Функция для подготовки строки краткой сравнительной сводки."""
        if first_value == second_value:
            change = {"symbol": "•", "text": "Без изменений", "class": "change-neutral"}
        elif first_value and not second_value:
            change = {"symbol": "✓", "text": "Стало лучше", "class": "change-good"}
        else:
            change = {"symbol": "✕", "text": "Стало хуже", "class": "change-bad"}
        return {
            "label": label,
            "first_value": "Да" if first_value else "Нет",
            "second_value": "Да" if second_value else "Нет",
            "change": change,
        }

    def _build_change_marker(self, first_value: float | None, second_value: float | None, better_when: str) -> dict:
        """Функция для выбора маркера изменения между двумя значениями."""
        if first_value is None or second_value is None:
            return {"symbol": "=", "text": "n/a", "class": "change-neutral"}
        if abs(first_value - second_value) < 1e-9:
            return {"symbol": "=", "text": "Без изменений", "class": "change-neutral"}
        if better_when == "lower":
            improved = second_value < first_value
        else:
            improved = second_value > first_value
        if improved:
            return {"symbol": "↑", "text": "Улучшение", "class": "change-good"}
        return {"symbol": "↓", "text": "Ухудшение", "class": "change-bad"}

    def _build_profile_change_marker(self, first_value: float | None, second_value: float | None) -> dict:
        """Функция для выбора маркера изменения по попаданию в профиль."""
        if first_value is None or second_value is None:
            return {"symbol": "=", "text": "n/a", "class": "change-neutral"}
        first_distance = abs(first_value - 100.0)
        second_distance = abs(second_value - 100.0)
        if abs(first_distance - second_distance) < 1e-9:
            return {"symbol": "=", "text": "Без изменений", "class": "change-neutral"}
        if second_distance < first_distance:
            return {"symbol": "↑", "text": "Ближе к профилю", "class": "change-good"}
        return {"symbol": "↓", "text": "Дальше от профиля", "class": "change-bad"}

    def _ms_to_seconds(self, value: float | None) -> float | None:
        """Функция для перевода миллисекунд в секунды."""
        if value is None:
            return None
        return float(value) / 1000.0
