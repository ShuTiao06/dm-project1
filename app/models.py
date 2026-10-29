from typing import Literal, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Account(StrictModel):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_\-\u4e00-\u9fff]+$')
    password: str = Field(min_length=8, max_length=128)


class Limits(StrictModel):
    min_choices: int | None = Field(default=None, ge=0, le=100)
    max_choices: int | None = Field(default=None, ge=0, le=100)
    min_length: int | None = Field(default=None, ge=0, le=10000)
    max_length: int | None = Field(default=None, ge=0, le=10000)
    min_value: float | None = None
    max_value: float | None = None
    integer: bool = False


class Rule(StrictModel):
    op: Literal['eq', 'contains', 'contains_all', 'gt', 'gte', 'lt', 'lte', 'between']
    value: Any
    target: str = Field(min_length=1, max_length=40)


class QuestionSource(StrictModel):
    root_id: str = Field(pattern=r'^[a-f0-9]{24}$')
    version_id: str = Field(pattern=r'^[a-f0-9]{24}$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class Question(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,39}$')
    title: str = Field(min_length=1, max_length=300)
    type: Literal['single', 'multiple', 'text', 'number']
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=100)
    validation: Limits = Field(default_factory=Limits)
    rules: list[Rule] = Field(default_factory=list, max_length=50)
    source: QuestionSource | None = None

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, v):
        if not v.strip():
            raise ValueError('题目标题不能为空')
        return v.strip()


class SurveyInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=3000)
    allow_anonymous: bool = True
    allow_multiple: bool = False
    deadline: datetime | None = None
    questions: list[Question] = Field(default_factory=list, max_length=100)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, v):
        if not v.strip():
            raise ValueError('问卷标题不能为空')
        return v.strip()

    @field_validator('deadline')
    @classmethod
    def timezone_required(cls, v):
        if v is not None and v.utcoffset() is None:
            raise ValueError('截止时间必须带时区，例如 2026-10-23T23:00:00+08:00')
        return v


class Submission(StrictModel):
    answers: dict[str, Any]
    anonymous: bool = False
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


class Preview(StrictModel):
    answers: dict[str, Any]

