from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Класс для хранения и чтения всех настроек приложения."""
    app_name: str = "LT Report Analyzer"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "change-me"

    postgres_db: str = "lt_reports"
    postgres_user: str = "lt_user"
    postgres_password: str = "lt_password"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    grafana_url: str = "http://localhost:3000"
    grafana_public_url: str = "http://localhost:3000"
    grafana_admin_user: str = "admin"
    grafana_admin_password: str = "admin"
    grafana_renderer_token: str = "lt-report-renderer-token"
    influxdb_url: str = "http://localhost:8086"
    influxdb_public_url: str = "http://localhost:8086"
    influxdb_username: str = "admin"
    influxdb_password: str = "admin12345"
    influxdb_org: str = "lt-report"
    influxdb_bucket: str = "lt-metrics"
    influxdb_token: str = "lt-report-token"
    prometheus_url: str = "http://localhost:9090"
    prometheus_public_url: str = "http://localhost:9090"
    prometheus_instance: str = "app-lt1:9100"
    prometheus_job: str = "node-exporter"
    report_timezone: str = "Europe/Moscow"
    grafana_dashboard_uid: str = "ffk6d9oj24kqoc"
    grafana_dashboard_slug: str = "load-testing-overview"

    default_admin_login: str = "admin"
    default_admin_password: str = "admin123"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def database_url(self) -> str:
        """Функция для сборки строки подключения к PostgreSQL."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
