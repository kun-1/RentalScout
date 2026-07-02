"""rentalscout.settings 的单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rentalscout.settings import Settings


def test_load_with_valid_values(tmp_path: Path) -> None:
    """有效 .env 应被正确解析, 类型自动转换。"""

    env_file = tmp_path / ".env"
    env_file.write_text(
        'AMAP_API_KEY="abc123"\n'
        "AMAP_WORKPLACE_LNG=121.4737\n"
        "AMAP_WORKPLACE_LAT=31.2304\n",
        encoding="utf-8",
    )

    settings = Settings.load(env_file)

    assert settings.amap_api_key == "abc123"
    assert settings.amap_workplace_lng == pytest.approx(121.4737)
    assert settings.amap_workplace_lat == pytest.approx(31.2304)
    assert isinstance(settings.amap_workplace_lng, float)
    assert isinstance(settings.amap_workplace_lat, float)


def test_load_with_empty_values(tmp_path: Path) -> None:
    """空值应转为 ``None``, 不抛异常。"""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "AMAP_API_KEY=\n"
        "AMAP_WORKPLACE_LNG=\n"
        "AMAP_WORKPLACE_LAT=\n",
        encoding="utf-8",
    )

    settings = Settings.load(env_file)

    assert settings.amap_api_key is None
    assert settings.amap_workplace_lng is None
    assert settings.amap_workplace_lat is None


def test_load_missing_file(tmp_path: Path) -> None:
    """不存在的 .env 应得到全 ``None`` 的实例。"""

    missing = tmp_path / "does-not-exist.env"

    settings = Settings.load(missing)

    assert settings.amap_api_key is None
    assert settings.amap_workplace_lng is None
    assert settings.amap_workplace_lat is None


def test_invalid_float_raises(tmp_path: Path) -> None:
    """非法浮点字符串应触发 ``ValidationError``。"""

    env_file = tmp_path / ".env"
    env_file.write_text("AMAP_WORKPLACE_LNG=not-a-number\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings.load(env_file)