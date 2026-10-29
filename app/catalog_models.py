from pydantic import Field, field_validator
from .models import StrictModel, Limits
from typing import Literal


class Definition(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    type: Literal['single', 'multiple', 'text', 'number']
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=100)
    validation: Limits = Field(default_factory=Limits)

    @field_validator('title')
    @classmethod
    def nonblank(cls, v):
        if not v.strip(): raise ValueError('标题不能为空')
        return v.strip()


class NewLibraryQuestion(StrictModel):
    definition: Definition
    note: str = Field(default='', max_length=1000)


class NewVersion(NewLibraryQuestion):
    parent_version_id: str = Field(pattern=r'^[a-f0-9]{24}$')


class ShareInput(StrictModel):
    username: str = Field(min_length=3, max_length=40)


class ImportInput(StrictModel):
    version_id: str = Field(pattern=r'^[a-f0-9]{24}$')
    local_id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,39}$')


class BankInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)

    @field_validator('name')
    @classmethod
    def nonblank(cls, v):
        if not v.strip(): raise ValueError('题库名称不能为空')
        return v.strip()


class BankItemInput(StrictModel):
    version_id: str = Field(pattern=r'^[a-f0-9]{24}$')

