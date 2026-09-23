from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobRequest(BaseModel):
    kind: Literal["video", "clip", "audio"]
    url: str | None = Field(default=None, max_length=2048)
    source_id: str | None = None
    resolution: int | None = Field(default=None, ge=144, le=8640)
    start: str | float | int | None = None
    end: str | float | int | None = None
    audio_format: Literal["m4a", "mp3"] = "m4a"

    @model_validator(mode="after")
    def validate_source(self):
        if bool(self.url) == bool(self.source_id):
            raise ValueError("Informe exatamente uma URL ou source_id.")
        if self.kind == "clip" and (self.start is None or self.end is None):
            raise ValueError("Início e fim são obrigatórios para cortes.")
        return self

