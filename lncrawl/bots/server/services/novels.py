from typing import Any, List

from ..context import ServerContext
from ..exceptions import AppErrors
from ..models.novel import Artifact, Novel
from ..models.pagination import Paginated
from ..models.user import User, UserRole


class NovelService:
    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._db = ctx.db

    def list(
        self,
        search: str = '',
        offset: int = 0,
        limit: int = 20,
        with_orphans: bool = False
    ) -> Paginated[Novel]:
        
        query = {}
        if not with_orphans:
            query["orphan"] = {"$ne": True}
            query["title"] = {"$nin": ["...", "", None]}

        if search:
            query["title"] = {"$regex": search, "$options": "i"}

        total = self._db.novels.count_documents(query)
        cursor = self._db.novels.find(query).sort("updated_at", -1).skip(offset).limit(limit)
        items = [Novel(**doc) for doc in cursor]

        return Paginated(
            total=total,
            offset=offset,
            limit=limit,
            items=items,
        )

    def get(self, novel_id: str) -> Novel:
        data = self._db.novels.find_one({"_id": novel_id})
        if not data:
            raise AppErrors.no_such_novel
        return Novel(**data)

    def delete(self, novel_id: str, user: User) -> bool:
        if user.role != UserRole.ADMIN:
            raise AppErrors.forbidden
        
        result = self._db.novels.delete_one({"_id": novel_id})
        # Also delete related artifacts and jobs if needed, but MongoDB doesn't cascade automatically
        # For simplicity/performance on free tier we might leave orphans or clean manually
        return True

    def get_artifacts(self, novel_id: str) -> List[Artifact]:
        data = self._db.novels.find_one({"_id": novel_id})
        if not data:
            raise AppErrors.no_such_novel
        
        cursor = self._db.artifacts.find({"novel_id": novel_id})
        return [Artifact(**doc) for doc in cursor]