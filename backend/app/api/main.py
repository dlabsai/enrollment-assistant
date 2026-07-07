from fastapi import APIRouter

from app.api.routes import (
    analytics,
    auth,
    chat,
    consent,
    conversations,
    evals,
    feedback,
    messages,
    models,
    prompts,
    rag,
    rbac,
    usage,
    utils,
)

api_router = APIRouter()
api_router.include_router(analytics.router)
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(consent.router)
api_router.include_router(conversations.router)
api_router.include_router(evals.router)
api_router.include_router(feedback.router)
api_router.include_router(messages.router)
api_router.include_router(models.router)
api_router.include_router(prompts.router)
api_router.include_router(rag.router)
api_router.include_router(rbac.router)
api_router.include_router(usage.router)
api_router.include_router(utils.router)
