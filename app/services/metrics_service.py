from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.models import TestRun


class MetricsService:
    """Сервис для получения бизнес- и аппаратных метрик из внешних систем."""
    def __init__(self) -> None:
        """Функция для инициализации сервиса метрик."""
        self._report_tz = ZoneInfo(settings.report_timezone)

    def fetch_influx_business_metrics(self, test_run: TestRun) -> dict:
        """Забирает бизнес-метрики по тесту за выбранное окно времени."""
        start_utc, stop_utc = self.get_test_window_utc(test_run)
        bucket = test_run.influx_bucket or settings.influxdb_bucket
        operation_metrics = self._fetch_operation_metrics(bucket, start_utc, stop_utc)
        transaction_metrics = self._fetch_transaction_metrics(bucket, start_utc, stop_utc)
        error_summary = self._fetch_error_summary(bucket, start_utc, stop_utc)
        throughput_summary = self._fetch_throughput_summary(bucket, start_utc, stop_utc)
        threads_summary = self._fetch_threads_summary(bucket, start_utc, stop_utc)

        return {
            "operation_metrics": operation_metrics,
            "transaction_metrics": transaction_metrics,
            "error_count": error_summary["error_count"],
            "total_requests": error_summary["total_requests"],
            "error_percent": error_summary["error_percent"],
            "throughput_peak_rps": throughput_summary["throughput_peak_rps"],
            "max_threads": threads_summary["max_threads"],
        }

    def fetch_prometheus_system_metrics(self, test_run: TestRun) -> dict:
        """Получает аппаратные метрики, которые потом используются в отчете."""
        start_utc, stop_utc = self.get_test_window_utc(test_run)
        prometheus_url = test_run.prometheus_url or settings.prometheus_url
        cpu_query = (
            f'100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{{instance="{settings.prometheus_instance}",'
            f'job="{settings.prometheus_job}",mode="idle"}}[5m])))'
        )
        ram_query = (
            f'100 * (1 - (node_memory_MemAvailable_bytes{{instance="{settings.prometheus_instance}",job="{settings.prometheus_job}"}} '
            f'/ node_memory_MemTotal_bytes{{instance="{settings.prometheus_instance}",job="{settings.prometheus_job}"}}))'
        )
        disk_query = (
            f'100 * (1 - (node_filesystem_avail_bytes{{instance="{settings.prometheus_instance}",job="{settings.prometheus_job}",mountpoint="C:\\\\"}} '
            f'/ node_filesystem_size_bytes{{instance="{settings.prometheus_instance}",job="{settings.prometheus_job}",mountpoint="C:\\\\"}}))'
        )

        cpu_series = self._query_prometheus_range(prometheus_url, cpu_query, start_utc, stop_utc)
        ram_series = self._query_prometheus_range(prometheus_url, ram_query, start_utc, stop_utc)
        disk_series = self._query_prometheus_range(prometheus_url, disk_query, start_utc, stop_utc)

        return {
            "cpu_usage_max": self._max_value(cpu_series),
            "ram_usage_max": self._max_value(ram_series),
            "disk_usage_max": self._max_value(disk_series),
        }

    def get_test_window_utc(self, test_run: TestRun) -> tuple[datetime, datetime]:
        """Переводит время теста в UTC, чтобы все запросы были в одном формате."""
        return self._to_utc(test_run.started_at), self._to_utc(test_run.finished_at)

    def _fetch_operation_metrics(
        self,
        bucket: str,
        start_utc: datetime,
        stop_utc: datetime,
    ) -> dict[str, dict]:
        """Функция для получения метрик по операциям из InfluxDB."""
        p95_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> group(columns: ["operation"])
  |> window(every: 1m)
  |> quantile(q: 0.95, method: "estimate_tdigest")
  |> duplicate(column: "_stop", as: "_time")
  |> window(every: inf)
  |> group(columns: ["operation"])
  |> max()
  |> keep(columns: ["operation", "_value"])
  |> yield(name: "operation_p95_max")
"""
        count_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> group(columns: ["operation"])
  |> count()
  |> keep(columns: ["operation", "_value"])
  |> yield(name: "operation_counts")
"""
        error_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "success")
  |> map(fn: (r) => ({{ r with _value: if r._value == true then 0.0 else 1.0 }}))
  |> group(columns: ["operation"])
  |> sum()
  |> keep(columns: ["operation", "_value"])
  |> yield(name: "operation_errors")
"""
        slowest_request_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "request")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> group(columns: ["operation", "request"])
  |> max()
  |> group(columns: ["operation"])
  |> sort(columns: ["_value"], desc: true)
  |> first()
  |> keep(columns: ["operation", "request", "_value"])
  |> yield(name: "slowest_requests")
"""

        operation_metrics: dict[str, dict] = defaultdict(
            lambda: {"p95_max_ms": None, "count_total": 0, "errors": 0, "slowest_request_name": None, "slowest_request_ms": None}
        )

        for row in self._query_influx_rows(p95_query):
            operation_name = row.get("operation")
            if operation_name:
                operation_metrics[operation_name]["p95_max_ms"] = self._to_float(row.get("_value"))

        for row in self._query_influx_rows(count_query):
            operation_name = row.get("operation")
            if operation_name:
                operation_metrics[operation_name]["count_total"] = int(self._to_float(row.get("_value"), default=0.0))

        for row in self._query_influx_rows(error_query):
            operation_name = row.get("operation")
            if operation_name:
                operation_metrics[operation_name]["errors"] = int(self._to_float(row.get("_value"), default=0.0))

        for row in self._query_influx_rows(slowest_request_query):
            operation_name = row.get("operation")
            if operation_name:
                operation_metrics[operation_name]["slowest_request_name"] = row.get("request")
                operation_metrics[operation_name]["slowest_request_ms"] = self._to_float(row.get("_value"))

        return dict(operation_metrics)

    def _fetch_error_summary(
        self,
        bucket: str,
        start_utc: datetime,
        stop_utc: datetime,
    ) -> dict[str, float]:
        """Функция для подсчета общего количества и процента ошибок по тесту."""
        total_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "request")
  |> filter(fn: (r) => r._field == "success")
  |> group()
  |> count()
  |> yield(name: "total_requests")
"""
        error_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "request")
  |> filter(fn: (r) => r._field == "success")
  |> map(fn: (r) => ({{ r with _value: if r._value == true then 0.0 else 1.0 }}))
  |> group()
  |> sum()
  |> yield(name: "total_errors")
"""
        total_rows = self._query_influx_rows(total_query)
        error_rows = self._query_influx_rows(error_query)
        total_requests = int(self._to_float(total_rows[0].get("_value"), default=0.0)) if total_rows else 0
        error_count = int(self._to_float(error_rows[0].get("_value"), default=0.0)) if error_rows else 0
        error_percent = (error_count / total_requests * 100.0) if total_requests else 0.0
        return {
            "total_requests": total_requests,
            "error_count": error_count,
            "error_percent": error_percent,
        }

    def _fetch_throughput_summary(
        self,
        bucket: str,
        start_utc: datetime,
        stop_utc: datetime,
    ) -> dict[str, float]:
        """Функция для получения пикового throughput за время теста."""
        query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "request")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> aggregateWindow(every: 1m, fn: count, createEmpty: false)
  |> map(fn: (r) => ({{ r with _value: float(v: r._value) / 60.0 }}))
  |> keep(columns: ["_time", "_value"])
  |> yield(name: "throughput")
"""
        rows = self._query_influx_rows(query)
        values = [self._to_float(row.get("_value"), default=0.0) for row in rows]
        return {"throughput_peak_rps": max(values) if values else 0.0}

    def _fetch_transaction_metrics(
        self,
        bucket: str,
        start_utc: datetime,
        stop_utc: datetime,
    ) -> list[dict]:
        """Функция для получения общей сводки по транзакциям из InfluxDB."""
        p95_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> group(columns: ["operation", "transaction"])
  |> window(every: 1m)
  |> quantile(q: 0.95, method: "estimate_tdigest")
  |> duplicate(column: "_stop", as: "_time")
  |> window(every: inf)
  |> group(columns: ["operation", "transaction"])
  |> max()
  |> keep(columns: ["operation", "transaction", "_value"])
  |> yield(name: "transaction_p95_max")
"""
        count_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "elapsed_ms")
  |> group(columns: ["operation", "transaction"])
  |> count()
  |> keep(columns: ["operation", "transaction", "_value"])
  |> yield(name: "transaction_counts")
"""
        error_query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "success")
  |> map(fn: (r) => ({{ r with _value: if r._value == true then 0.0 else 1.0 }}))
  |> group(columns: ["operation", "transaction"])
  |> sum()
  |> keep(columns: ["operation", "transaction", "_value"])
  |> yield(name: "transaction_errors")
"""

        metrics: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"operation_name": "", "transaction_name": "", "p95_max_ms": None, "count_total": 0, "errors": 0}
        )

        for row in self._query_influx_rows(p95_query):
            key = (row.get("operation") or "", row.get("transaction") or "")
            metrics[key]["operation_name"] = key[0]
            metrics[key]["transaction_name"] = key[1]
            metrics[key]["p95_max_ms"] = self._to_float(row.get("_value"))

        for row in self._query_influx_rows(count_query):
            key = (row.get("operation") or "", row.get("transaction") or "")
            metrics[key]["operation_name"] = key[0]
            metrics[key]["transaction_name"] = key[1]
            metrics[key]["count_total"] = int(self._to_float(row.get("_value"), default=0.0))

        for row in self._query_influx_rows(error_query):
            key = (row.get("operation") or "", row.get("transaction") or "")
            metrics[key]["operation_name"] = key[0]
            metrics[key]["transaction_name"] = key[1]
            metrics[key]["errors"] = int(self._to_float(row.get("_value"), default=0.0))

        return sorted(metrics.values(), key=lambda item: (item["operation_name"], item["transaction_name"]))

    def _fetch_threads_summary(
        self,
        bucket: str,
        start_utc: datetime,
        stop_utc: datetime,
    ) -> dict[str, int]:
        """Функция для получения максимального количества потоков за тест."""
        query = f"""
from(bucket: "{bucket}")
  |> range(start: {self._flux_time(start_utc)}, stop: {self._flux_time(stop_utc)})
  |> filter(fn: (r) => r._measurement == "jmeter_samples")
  |> filter(fn: (r) => r.sampler_type == "transaction")
  |> filter(fn: (r) => r._field == "all_threads")
  |> max()
  |> yield(name: "max_threads")
"""
        rows = self._query_influx_rows(query)
        max_threads = int(self._to_float(rows[0].get("_value"), default=0.0)) if rows else 0
        return {"max_threads": max_threads}

    def _query_influx_rows(self, flux_query: str) -> list[dict[str, str]]:
        """Функция для выполнения Flux-запроса к InfluxDB."""
        headers = {
            "Authorization": f"Token {settings.influxdb_token}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux",
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{settings.influxdb_url}/api/v2/query",
                params={"org": settings.influxdb_org},
                headers=headers,
                content=flux_query.encode("utf-8"),
            )
            response.raise_for_status()

        cleaned_lines = [line for line in response.text.splitlines() if line and not line.startswith("#")]
        reader = csv.DictReader(io.StringIO("\n".join(cleaned_lines)))
        rows: list[dict[str, str]] = []
        for row in reader:
            if not row or not row.get("result", None) and row.get("_value") in (None, ""):
                continue
            rows.append(row)
        return rows

    def _query_prometheus_range(self, prometheus_url: str, query: str, start_utc: datetime, stop_utc: datetime) -> list[float]:
        """Функция для выполнения range-запроса к Prometheus по интервалу теста."""
        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                f"{prometheus_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start_utc.timestamp(),
                    "end": stop_utc.timestamp(),
                    "step": "60s",
                },
            )
            response.raise_for_status()

        data = response.json().get("data", {})
        result = data.get("result", [])
        values: list[float] = []
        for series in result:
            for _, raw_value in series.get("values", []):
                try:
                    values.append(float(raw_value))
                except (TypeError, ValueError):
                    continue
        return values

    def _to_utc(self, value: datetime) -> datetime:
        """Функция для перевода даты и времени в UTC."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=self._report_tz)
        return value.astimezone(timezone.utc)

    def _flux_time(self, value: datetime) -> str:
        """Функция для подготовки времени в формате Flux."""
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _to_float(self, value: str | None, default: float | None = None) -> float | None:
        """Функция для безопасного преобразования значения в число."""
        if value in (None, ""):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _max_value(self, values: list[float]) -> float | None:
        """Функция для получения максимального значения из списка."""
        return max(values) if values else None
