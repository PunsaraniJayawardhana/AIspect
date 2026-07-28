import asyncio
import uuid
from typing import Dict, Optional
from dataclasses import dataclass, field


def _project_key_from_story_key(story_key: str) -> str:
    """Derive the project key from a story key like 'EXC-1' -> 'EXC'."""
    return story_key.split("-")[0] if story_key else ""


@dataclass
class Job:
    id: str
    story_key: str
    project_key: str = ""
    status: str = "pending"       # pending | running | completed | failed
    current_step: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class JobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}

    def create(self, story_key: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            story_key=story_key,
            project_key=_project_key_from_story_key(story_key),
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)


job_store = JobStore()
