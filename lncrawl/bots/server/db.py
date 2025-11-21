import logging
from pymongo import MongoClient
from .context import ServerContext

logger = logging.getLogger(__name__)


class DB:
    def __init__(self, ctx: ServerContext) -> None:
        self.client = MongoClient(ctx.config.server.mongodb_url)
        self.db = self.client[ctx.config.server.database_name]

    def close(self):
        self.client.close()

    def prepare(self):
        logger.info('Ensuring indexes...')
        # Unique constraints
        self.db.users.create_index("email", unique=True)
        self.db.novels.create_index("url", unique=True)
        
        # Performance indexes
        self.db.jobs.create_index("user_id")
        self.db.jobs.create_index("status")
        self.db.jobs.create_index("priority")
        self.db.jobs.create_index("created_at")
        self.db.artifacts.create_index("novel_id")
        self.db.artifacts.create_index("job_id")

    @property
    def users(self):
        return self.db.users

    @property
    def jobs(self):
        return self.db.jobs

    @property
    def novels(self):
        return self.db.novels

    @property
    def artifacts(self):
        return self.db.artifacts
        
    @property
    def verified_emails(self):
        return self.db.verified_emails