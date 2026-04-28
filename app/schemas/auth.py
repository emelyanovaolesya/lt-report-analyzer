from pydantic import BaseModel, EmailStr


class LoginForm(BaseModel):
    """Класс для описания данных формы авторизации."""
    login: str
    password: str


class UserCreate(BaseModel):
    """Класс для описания данных формы создания пользователя."""
    login: str
    email: EmailStr
    password: str
    role: str
    project_id: int | None = None
