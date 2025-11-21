import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field

from ._base import BaseTable
from .enums import OutputFormat


class Novel(BaseTable):
    url: str = Field(description="The novel page url")
    orphan: Optional[bool] = Field(default=True, description='False if novel info available')

    title: Optional[str] = Field(default=None, description="The novel title")
    cover: Optional[str] = Field(default=None, description="The novel cover image", exclude=True)
    authors: Optional[str] = Field(default=None, description="The novel author")
    synopsis: Optional[str] = Field(default=None, description="The novel synopsis")
    tags: Optional[List[str]] = Field(default=None, description="Tags")

    volume_count: Optional[int] = Field(default=None, description="Volume count")
    chapter_count: Optional[int] = Field(default=None, description="Chapter count")

    extra: Dict[str, Any] = Field(default={}, description="Extra field")


class Artifact(BaseTable):
    novel_id: str = Field(description="Novel ID")
    job_id: Optional[str] = Field(default=None, description="Job ID")

    output_file: str = Field(description="Output file path", exclude=True)
    format: OutputFormat = Field(description="The output format of the artifact")

    extra: Dict[str, Any] = Field(default={}, description="Extra field")

    @computed_field  # type:ignore
    @property
    def file_name(self) -> str:
        '''Output file name'''
        return os.path.basename(self.output_file)

    @computed_field  # type:ignore
    @property
    def is_available(self) -> bool:
        '''Output file is available'''
        return os.path.isfile(self.output_file)

    @computed_field  # type:ignore
    @property
    def file_size(self) -> Optional[int]:
        '''Output file size in bytes'''
        try:
            stat = os.stat(self.output_file)
            return stat.st_size
        except Exception:
            return None


class NovelChapter(BaseModel):
    id: int
    title: str
    hash: str


class NovelVolume(BaseModel):
    id: int
    title: str
    chapters: List[NovelChapter] = []


class NovelChapterContent(BaseModel):
    id: int
    title: str
    body: str
    volume_id: int
    volume: str
    prev: Optional[NovelChapter] = None
    next: Optional[NovelChapter] = None