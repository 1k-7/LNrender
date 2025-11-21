import uuid
from typing import Optional
from pydantic import BaseModel, Field
from ..utils.time_utils import current_timestamp


def generate_uuid():
    return uuid.uuid4().hex


class BaseTable(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    created_at: int = Field(default_factory=current_timestamp)
    updated_at: int = Field(default_factory=current_timestamp)

    class Config:
        populate_by_name = True