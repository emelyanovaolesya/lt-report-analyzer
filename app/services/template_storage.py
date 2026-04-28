from pathlib import Path


TEMPLATE_STORAGE_DIR = Path("report_templates")


def ensure_template_storage_dir() -> None:
    """Функция для создания папки с шаблонами отчетов при ее отсутствии."""
    TEMPLATE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def to_storage_path(path: Path) -> str:
    """Функция для перевода пути к шаблону в относительный формат хранения."""
    return path.relative_to(Path.cwd()).as_posix()


def resolve_storage_path(file_path: str) -> Path:
    """Функция для преобразования пути из БД в реальный путь на диске."""
    candidate = Path(file_path)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate
