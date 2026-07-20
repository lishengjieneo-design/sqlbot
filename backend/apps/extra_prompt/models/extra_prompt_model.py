from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Identity, Text
from sqlmodel import Field, SQLModel


class ExtraPromptTypeEnum(str, Enum):
    GENERATE_SQL = "GENERATE_SQL"


class ExtraPrompt(SQLModel, table=True):
    __tablename__ = "extra_prompt"

    id: Optional[int] = Field(sa_column=Column(BigInteger, Identity(always=True), primary_key=True))
    oid: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True, default=1))
    datasource_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    type: str = Field(max_length=20, default=ExtraPromptTypeEnum.GENERATE_SQL.value)
    description: Optional[str] = Field(max_length=255, default=None)
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    enabled: bool = Field(sa_column=Column(Boolean, nullable=False, default=True))
    published_version_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    draft_version_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    create_time: Optional[datetime] = Field(sa_column=Column(DateTime(timezone=False), nullable=True))
    update_time: Optional[datetime] = Field(sa_column=Column(DateTime(timezone=False), nullable=True))


class ExtraPromptInfo(BaseModel):
    id: Optional[int] = None
    oid: Optional[int] = None
    datasource_id: int
    datasource_name: Optional[str] = None
    type: str = ExtraPromptTypeEnum.GENERATE_SQL.value
    description: Optional[str] = None
    prompt: str
    enabled: bool = True
    published_version_id: Optional[int] = None
    draft_version_id: Optional[int] = None
    published_version_no: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None

