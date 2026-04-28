from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class LoadProfile(TimestampMixin, Base):
    """Профиль нагрузочного тестирования с набором операций и их параметров."""
    __tablename__ = "load_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))

    project = relationship("Project", back_populates="load_profiles")
    operations = relationship("LoadProfileOperation", back_populates="load_profile", cascade="all, delete-orphan")
    tests = relationship("TestRun", back_populates="load_profile")
