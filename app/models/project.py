from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Project(TimestampMixin, Base):
    """Модель проекта, внутри которого хранятся профили, тесты и отчеты."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)

    users = relationship("User", back_populates="project")
    load_profiles = relationship("LoadProfile", back_populates="project")
    reports = relationship("Report", back_populates="project")
