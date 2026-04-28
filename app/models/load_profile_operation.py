from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LoadProfileOperation(Base):
    """Отдельная операция внутри профиля НТ с SLA и ожидаемым количеством вызовов."""
    __tablename__ = "load_profile_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    load_profile_id: Mapped[int] = mapped_column(ForeignKey("load_profiles.id"))
    name: Mapped[str] = mapped_column(String(255))
    executions_per_hour: Mapped[int] = mapped_column(Integer, default=0)
    sla_ms: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    load_profile = relationship("LoadProfile", back_populates="operations")
