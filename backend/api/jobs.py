import json
import asyncio
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jobs.job_store import job_store
from pipeline.orchestrator import process_one_story

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class StartJobRequest(BaseModel):
    story_key: str
    app_url: Optional[str] = None


@router.post("")
async def start_job(req: StartJobRequest, background: BackgroundTasks):
    """Kick off the pipeline for ONE story. Returns the job ID immediately."""
    job = job_store.create(req.story_key)
    background.add_task(process_one_story, job, req.story_key, req.app_url)
    return {"job_id": job.id, "story_key": req.story_key}


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Snapshot the current state of a job (for page refreshes)."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "story_key": job.story_key,
        "status": job.status,
        "current_step": job.current_step,
        "result": job.result,
        "error": job.error,
    }


@router.get("/{job_id}/stream")
async def stream_job(job_id: str):
    """Server-Sent Events stream of progress for one job."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    async def event_generator():
        # If the job already finished before the client subscribed, replay
        if job.status in ("completed", "failed"):
            final = {
                "step": "done" if job.status == "completed" else "error",
                "payload": job.result if job.status == "completed"
                           else {"message": job.error},
                "final": True,
            }
            yield f"data: {json.dumps(final)}\n\n"
            return

        while True:
            try:
                event = await asyncio.wait_for(
                    job.event_queue.get(), timeout=30.0
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            yield f"data: {json.dumps(event)}\n\n"
            if event["step"] in ("done", "error"):
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")
