from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReportTemplate(Base):
    """Шаблон отчета, на основе которого генерируется итоговый HTML."""
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    file_path: Mapped[str] = mapped_column(String(500))

    reports = relationship("Report", back_populates="template")
