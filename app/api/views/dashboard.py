from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.services.dashboard_service import build_dashboard_context


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def index(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Функция для формирования главной страницы со статистикой и последними событиями."""
    context = build_dashboard_context(db, current_user)
    context.update(
        {
            "request": request,
            "user": current_user,
            "resources": {
                "grafana": settings.grafana_public_url,
                "influxdb": settings.influxdb_public_url,
                "prometheus": settings.prometheus_public_url,
            },
        }
    )
    return templates.TemplateResponse("dashboard.html", context)
