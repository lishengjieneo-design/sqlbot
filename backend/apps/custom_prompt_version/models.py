"""Models for custom_prompt versioning (local overlay on xpack table)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Column, DateTime, Identity, Integer, String, Text
from sqlmodel import Field as SQLField, SQLModel


class CustomPromptVersion(SQLModel, table=True):
    __tablename__ = 'custom_prompt_version'
    id: Optional[int] = SQLField(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    prompt_id: int = SQLField(sa_column=Column(BigInteger, nullable=False, index=True))
    version_no: int = SQLField(sa_column=Column(Integer, nullable=False))
    prompt: str = SQLField(sa_column=Column(Text, nullable=False))
    change_note: Optional[str] = SQLField(default=None, sa_column=Column(String(255), nullable=True))
    created_by: Optional[int] = SQLField(default=None, sa_column=Column(BigInteger, nullable=True))
    create_time: Optional[datetime] = SQLField(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))


class CustomPromptVersionInfo(BaseModel):
    id: Optional[int] = None
    prompt_id: Optional[int] = None
    version_no: Optional[int] = None
    prompt: Optional[str] = None
    change_note: Optional[str] = None
    created_by: Optional[int] = None
    create_time: Optional[datetime] = None
    is_published: bool = False
    is_draft: bool = False


class CustomPromptDraftSave(BaseModel):
    prompt: str
    change_note: Optional[str] = None


class CustomPromptVersioningState(BaseModel):
    prompt_id: int
    published_version_id: Optional[int] = None
    draft_version_id: Optional[int] = None
    published: Optional[CustomPromptVersionInfo] = None
    draft: Optional[CustomPromptVersionInfo] = None
    versions: List[CustomPromptVersionInfo] = Field(default_factory=list)
