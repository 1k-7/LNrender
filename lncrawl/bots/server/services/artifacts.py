import os
from typing import Optional

from ..context import ServerContext
from ..exceptions import AppErrors
from ..models.enums import UserRole
from ..models.novel import Artifact
from ..models.pagination import Paginated
from ..models.user import User
from ..utils.time_utils import current_timestamp


class ArtifactService:
    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._db = ctx.db

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        novel_id: Optional[str] = None,
    ) -> Paginated[Artifact]:
        query = {}
        if novel_id:
            query["novel_id"] = novel_id
            
        total = self._db.artifacts.count_documents(query)
        cursor = self._db.artifacts.find(query).sort("updated_at", -1).skip(offset).limit(limit)
        items = [Artifact(**doc) for doc in cursor]

        return Paginated(
            total=total,
            offset=offset,
            limit=limit,
            items=items,
        )

    def get(self, artifact_id: str) -> Artifact:
        data = self._db.artifacts.find_one({"_id": artifact_id})
        if not data:
            raise AppErrors.no_such_artifact
        return Artifact(**data)

    def delete(self, artifact_id: str, user: User) -> bool:
        if user.role != UserRole.ADMIN:
            raise AppErrors.forbidden
        
        data = self._db.artifacts.find_one({"_id": artifact_id})
        if not data:
            raise AppErrors.no_such_artifact
            
        self._db.artifacts.delete_one({"_id": artifact_id})
        return True

    def upsert(self, item: Artifact):
        old_file = None
        new_file = item.output_file

        query = {
            "novel_id": item.novel_id,
            "format": item.format
        }
        existing = self._db.artifacts.find_one(query)

        if not existing:
            self._db.artifacts.insert_one(item.model_dump(by_alias=True))
        else:
            old_file = existing.get("output_file")
            update_data = {
                "job_id": item.job_id,
                "output_file": item.output_file,
                "updated_at": current_timestamp()
            }
            self._db.artifacts.update_one({"_id": existing["_id"]}, {"$set": update_data})

        # remove old file
        if old_file and old_file != new_file and os.path.isfile(old_file):
            try:
                os.remove(old_file)
            except OSError:
                pass