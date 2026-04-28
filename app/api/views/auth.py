from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services.auth_service import authenticate_user


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request):
    """Функция для открытия страницы авторизации."""
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login(request: Request, login: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Функция для обработки входа пользователя в систему."""
    user = authenticate_user(db, login, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=400,
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request, _: object = Depends(get_current_user)):
    """Функция для выхода пользователя из системы через форму интерфейса."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
def logout_page(request: Request, _: object = Depends(get_current_user)):
    """Функция для выхода пользователя из системы при переходе по прямой ссылке."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
