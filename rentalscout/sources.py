"""数据源入口配置。"""

from dataclasses import dataclass

from rentalscout.schemas.raw import SourceName


@dataclass(frozen=True)
class SourceEntry:
    """一个公开数据源入口。"""

    source: SourceName
    name: str
    url: str


BEIKE_PHASE1_BASE = "https://sh.zu.ke.com/zufang/pudong"
BEIKE_PHASE1_SUFFIX = "rt200600000001l0brp3500erp6000"

DEFAULT_SOURCE_ENTRIES: tuple[SourceEntry, ...] = (
    SourceEntry(
        source=SourceName.BEIKE,
        name="贝壳上海租房(浦东整租一居 0-6000)",
        url=f"{BEIKE_PHASE1_BASE}/{BEIKE_PHASE1_SUFFIX}",
    ),
    SourceEntry(
        source=SourceName.WELLCEE,
        name="Wellcee 上海租房",
        url="https://www.wellcee.com/rent-apartment/shanghai/list?cityId=15102233103895305",
    ),
)
