from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Функция для хеширования пароля перед сохранением в базу."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Функция для проверки соответствия введенного пароля сохраненному хешу."""
    return pwd_context.verify(plain_password, hashed_password)
