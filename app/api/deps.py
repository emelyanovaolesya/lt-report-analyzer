from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import User


def get_db():
    """Функция для получения сессии базы данных внутри обработчика запроса."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Функция для получения текущего авторизованного пользователя из сессии."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    user = db.get(User, user_id)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_role(*roles: str) -> Callable:
    """Функция для ограничения доступа к маршруту по ролям пользователя."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        """Функция для внутренней проверки роли текущего пользователя."""
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return dependency
