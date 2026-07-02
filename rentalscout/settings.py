"""Shared project settings."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
ENV_FILE = PROJECT_ROOT / ".env"


def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    """读取项目根目录 .env, 不修改进程环境。"""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings(BaseModel):
    """类型化、校验后的项目配置。

    所有字段允许为空(返回 ``None``), 便于本地开发与 CI 共用同一份配置。
    """

    amap_api_key: str | None = None
    amap_workplace_lng: float | None = None
    amap_workplace_lat: float | None = None

    @field_validator("amap_api_key", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value: object) -> object:
        """空串/纯空白串视为 ``None``, 避免下游 KeyError。"""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("amap_workplace_lng", "amap_workplace_lat", mode="before")
    @classmethod
    def _coerce_optional_float(cls, value: object) -> object:
        """空串转 ``None``, 其它字符串按浮点解析。"""

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            return float(stripped)
        return value

    @classmethod
    def load(cls, path: Path = ENV_FILE) -> Self:
        """从 ``path`` 读取 .env 并构造已校验的 ``Settings`` 实例。"""

        raw = load_dotenv(path)
        return cls(
            amap_api_key=raw.get("AMAP_API_KEY"),
            amap_workplace_lng=raw.get("AMAP_WORKPLACE_LNG"),
            amap_workplace_lat=raw.get("AMAP_WORKPLACE_LAT"),
        )


def get_settings() -> Settings:
    """便捷访问器: 加载默认 .env 并返回 ``Settings``。"""

    return Settings.load()