from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class TestRun(TimestampMixin, Base):
    """Модель одного тестового прогона с окном времени и источниками метрик."""
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    load_profile_id: Mapped[int] = mapped_column(ForeignKey("load_profiles.id"))
    name: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    load_percent: Mapped[int] = mapped_column(Integer, default=100)
    influx_bucket: Mapped[str] = mapped_column(String(255), default="")
    prometheus_url: Mapped[str] = mapped_column(String(500), default="")

    load_profile = relationship("LoadProfile", back_populates="tests")
    reports = relationship("Report", back_populates="test_run", foreign_keys="Report.test_run_id")
