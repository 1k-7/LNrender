from typing import Any, List, Optional

from pydantic import HttpUrl

from ..context import ServerContext
from ..exceptions import AppErrors
from ..models.enums import JobPriority, JobStatus, RunState
from ..models.job import Job, JobDetail
from ..models.novel import Artifact, Novel
from ..models.pagination import Paginated
from ..models.user import User, UserRole
from ..utils.time_utils import current_timestamp
from .tier import JOB_PRIORITY_LEVEL
import uuid


class JobService:
    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._db = ctx.db

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        order: str = "desc",
        user_id: Optional[str] = None,
        novel_id: Optional[str] = None,
        priority: Optional[JobPriority] = None,
        status: Optional[JobStatus] = None,
        run_state: Optional[RunState] = None,
    ) -> Paginated[Job]:
        
        query = {}
        if user_id: query['user_id'] = user_id
        if novel_id: query['novel_id'] = novel_id
        if status: query['status'] = status
        if run_state: query['run_state'] = run_state
        if priority: query['priority'] = priority

        sort_dir = -1 if order == "desc" else 1
        
        total = self._db.jobs.count_documents(query)
        cursor = self._db.jobs.find(query).sort(sort_by, sort_dir).skip(offset).limit(limit)
        
        items = [Job(**doc) for doc in cursor]

        return Paginated(
            total=total,
            offset=offset,
            limit=limit,
            items=items,
        )

    async def create(self, url: HttpUrl, user: User):
        novel_url = str(url)
        
        # get or create novel
        novel_data = self._db.novels.find_one({"url": novel_url})
        if not novel_data:
            novel = Novel(url=novel_url)
            self._db.novels.insert_one(novel.model_dump(by_alias=True))
            novel_id = novel.id
        else:
            novel_id = novel_data["_id"]

        # create the job
        job = Job(
            user_id=user.id,
            novel_id=novel_id,
            url=novel_url,
            priority=JOB_PRIORITY_LEVEL[user.tier],
        )
        self._db.jobs.insert_one(job.model_dump(by_alias=True))
        return job

    def delete(self, job_id: str, user: User) -> bool:
        job_data = self._db.jobs.find_one({"_id": job_id})
        if not job_data:
            return True
        
        if job_data['user_id'] != user.id and user.role != UserRole.ADMIN:
            raise AppErrors.forbidden
            
        self._db.jobs.delete_one({"_id": job_id})
        return True

    def cancel(self, job_id: str, user: User) -> bool:
        job_data = self._db.jobs.find_one({"_id": job_id})
        if not job_data:
            return True
        
        if job_data.get('status') == JobStatus.COMPLETED:
            return True
            
        if job_data['user_id'] != user.id and user.role != UserRole.ADMIN:
            raise AppErrors.forbidden
            
        who = 'user' if job_data['user_id'] == user.id else 'admin'
        
        update = {
            "error": f'Canceled by {who}',
            "status": JobStatus.COMPLETED,
            "run_state": RunState.CANCELED,
            "updated_at": current_timestamp()
        }
        self._db.jobs.update_one({"_id": job_id}, {"$set": update})
        return True

    def get(self, job_id: str) -> JobDetail:
        job_data = self._db.jobs.find_one({"_id": job_id})
        if not job_data:
            raise AppErrors.no_such_job
        
        job = Job(**job_data)
        
        user_data = self._db.users.find_one({"_id": job.user_id})
        user = User(**user_data) if user_data else None
        
        novel_data = self._db.novels.find_one({"_id": job.novel_id})
        novel = Novel(**novel_data) if novel_data else None
        
        cursor = self._db.artifacts.find({"job_id": job.id})
        artifacts = [Artifact(**doc) for doc in cursor]

        return JobDetail(
            job=job,
            user=user,
            novel=novel,
            artifacts=artifacts,
        )

    def get_artifacts(self, job_id: str) -> List[Artifact]:
        cursor = self._db.artifacts.find({"job_id": job_id})
        return [Artifact(**doc) for doc in cursor]

    def get_novel(self, job_id: str) -> Novel:
        job_data = self._db.jobs.find_one({"_id": job_id})
        if not job_data:
            raise AppErrors.no_such_job
            
        novel_data = self._db.novels.find_one({"_id": job_data['novel_id']})
        if not novel_data:
            raise AppErrors.no_such_novel
            
        return Novel(**novel_data)