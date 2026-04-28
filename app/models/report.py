from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Report(TimestampMixin, Base):
    """Сформированный отчет по одному тесту или по паре тестов."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"))
    second_test_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_runs.id"), nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("report_templates.id"))
    name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    report_type: Mapped[str] = mapped_column(String(32), default="TARGET")
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")

    test_run = relationship("TestRun", back_populates="reports", foreign_keys=[test_run_id])
    second_test_run = relationship("TestRun", foreign_keys=[second_test_run_id])
    project = relationship("Project", back_populates="reports")
    author = relationship("User", back_populates="reports")
    template = relationship("ReportTemplate", back_populates="reports")
