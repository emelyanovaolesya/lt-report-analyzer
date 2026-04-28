from __future__ import annotations

import base64
from datetime import datetime

import httpx

from app.core.config import settings


class GrafanaService:
    """Сервис, который получает изображения панелей Grafana для вставки в отчет."""
    PANEL_IDS = {
        "response_p95": 10,
        "errors": 12,
        "throughput": 15,
        "threads": 11,
        "cpu": 2,
        "ram": 4,
        "disk": 3,
    }

    def render_report_panels(self, start_utc: datetime, stop_utc: datetime) -> dict[str, str | None]:
        """Рендерит нужные панели и возвращает их как картинки в base64."""
        rendered: dict[str, str | None] = {}
        for panel_name, panel_id in self.PANEL_IDS.items():
            try:
                rendered[panel_name] = self._render_panel(panel_id, start_utc, stop_utc)
            except Exception:
                rendered[panel_name] = None
        return rendered

    def _render_panel(self, panel_id: int, start_utc: datetime, stop_utc: datetime) -> str | None:
        """Функция для рендера одной панели Grafana за выбранный период."""
        params = {
            "orgId": 1,
            "panelId": panel_id,
            "from": int(start_utc.timestamp() * 1000),
            "to": int(stop_utc.timestamp() * 1000),
            "tz": settings.report_timezone,
            "width": 1400,
            "height": 520,
        }
        url = (
            f"{settings.grafana_url}/render/d-solo/"
            f"{settings.grafana_dashboard_uid}/{settings.grafana_dashboard_slug}"
        )

        with httpx.Client(timeout=120.0, auth=(settings.grafana_admin_user, settings.grafana_admin_password)) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:image/png;base64,{encoded}"
