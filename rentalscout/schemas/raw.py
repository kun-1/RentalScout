"""Schemas for raw crawl artifacts."""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class SourceName(StrEnum):
    """Supported rental listing sources."""

    BEIKE = "beike"
    WELLCEE = "wellcee"
    DOUBAN = "douban"
    XIAOHONGSHU = "xiaohongshu"


class RawPage(BaseModel):
    """A raw page or response captured before parsing."""

    source: SourceName
    url: HttpUrl
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status_code: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = None
    content_hash: str | None = None
    raw_path: Path | None = None
    raw_body: str | None = None
    request_meta: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @model_validator(mode="after")
    def require_artifact_or_error(self) -> "RawPage":
        """Require either raw content, a raw file path, or an error."""

        if self.raw_path is None and self.raw_body is None and not self.error_message:
            msg = "RawPage needs raw_path, raw_body, or error_message"
            raise ValueError(msg)
        return self
