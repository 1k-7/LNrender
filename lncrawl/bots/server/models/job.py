from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..utils.time_utils import current_timestamp
from ._base import BaseTable
from .enums import JobPriority, JobStatus, RunState
from .novel import Artifact, Novel
from .user import User


class Job(BaseTable):
    url: str = Field(description="Download link")

    user_id: str = Field(description="User ID")
    novel_id: Optional[str] = Field(default=None, description="Novel ID")

    priority: JobPriority = Field(default=JobPriority.LOW, description="The job priority")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Current status")
    run_state: Optional[RunState] = Field(default=None, description="State of the job in progress status")

    progress: int = Field(default=0, description="Download progress percentage")
    error: Optional[str] = Field(default=None, description='Error state in case of failure')
    started_at: Optional[int] = Field(default=None, description="Job start time (UNIX ms)")
    finished_at: Optional[int] = Field(default=None, description="Job finish time (UNIX ms)")

    extra: Dict[str, Any] = Field(default={}, description="Extra field")


class JobDetail(BaseModel):
    job: Job = Field(description='Job')
    user: Optional[User] = Field(description='User')
    novel: Optional[Novel] = Field(description='Novel')
    artifacts: Optional[List[Artifact]] = Field(description='Artifacts')


class JobRunnerHistoryItem(BaseModel):
    time: int = Field(description='UNIX timestamp (seconds)')
    job_id: str = Field(description='Job')
    user_id: str = Field(description='User')
    novel_id: Optional[str] = Field(description='Novel')
    status: JobStatus = Field(description="Current status")
    run_state: Optional[RunState] = Field(description="State of the job in progress status")


class JobRunnerHistory(BaseModel):
    running: bool = Field(description='Job runner status')
    history: List[JobRunnerHistoryItem] = Field(description='Runner history')