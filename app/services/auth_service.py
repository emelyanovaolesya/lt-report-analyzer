from typing import Optional

from sqlalchemy.orm import Session

from app.models import User
from app.services.security import verify_password


def authenticate_user(session: Session, login: str, password: str) -> Optional[User]:
    """Функция для проверки логина и пароля пользователя при входе в систему."""
    user = session.query(User).filter(User.login == login).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
