from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import FRONTEND_ORIGIN
from api import stories, jobs

app = FastAPI(title="AIspect API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stories.router)
app.include_router(jobs.router)


@app.get("/")
async def root():
    return {"service": "AIspect", "status": "ok"}