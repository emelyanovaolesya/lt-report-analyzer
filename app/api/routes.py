from fastapi import APIRouter

from app.api.views import auth, dashboard, pages


router = APIRouter()
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(pages.router)
