from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Общий миксин с датой создания, чтобы не дублировать поле в моделях."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
