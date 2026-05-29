"""Crawl pacing profiles, metrics, and adaptive state."""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rentalscout.settings import DATA_DIR

CRAWL_RUNS_DIR = DATA_DIR / "crawl_runs"
BEIKE_METRICS_PATH = CRAWL_RUNS_DIR / "beike_metrics.jsonl"
BEIKE_STATE_PATH = CRAWL_RUNS_DIR / "beike_state.json"


@dataclass(frozen=True)
class BeikeCrawlProfile:
    """Named pacing profile for Beike crawling."""

    name: str
    delay_min: float
    delay_max: float
    human_break_every: int
    human_break_min: float
    human_break_max: float

    @property
    def delay_range(self) -> tuple[float, float]:
        return self.delay_min, self.delay_max

    @property
    def human_break_range(self) -> tuple[float, float]:
        return self.human_break_min, self.human_break_max


BEIKE_PROFILES: dict[str, BeikeCrawlProfile] = {
    "fast": BeikeCrawlProfile("fast", 10.0, 20.0, 7, 60.0, 120.0),
    "balanced": BeikeCrawlProfile("balanced", 25.0, 45.0, 5, 180.0, 300.0),
    "safe": BeikeCrawlProfile("safe", 45.0, 75.0, 4, 300.0, 600.0),
    "ultra": BeikeCrawlProfile("ultra", 75.0, 120.0, 3, 600.0, 900.0),
}
BEIKE_PROFILE_ORDER = ("fast", "balanced", "safe", "ultra")


class BeikeCrawlControl:
    """Runtime controller for Beike pacing and observability."""

    def __init__(
        self,
        *,
        profile_name: str | None = None,
        adaptive: bool = False,
        delay_range: tuple[float, float] = (10.0, 15.0),
        human_break_every: int = 7,
        human_break_range: tuple[float, float] = (60.0, 120.0),
        metrics_path: Path = BEIKE_METRICS_PATH,
        state_path: Path = BEIKE_STATE_PATH,
    ) -> None:
        self.adaptive = adaptive
        self.metrics_path = metrics_path
        self.state_path = state_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        state = self._load_state()

        resolved_profile = profile_name
        if resolved_profile is None and adaptive:
            state_profile = state.get("recommended_profile")
            if isinstance(state_profile, str) and state_profile in BEIKE_PROFILES:
                resolved_profile = state_profile

        if resolved_profile:
            self.profile_name = resolved_profile
            profile = BEIKE_PROFILES[resolved_profile]
            self.delay_range = profile.delay_range
            self.human_break_every = profile.human_break_every
            self.human_break_range = profile.human_break_range
        else:
            self.profile_name = "manual"
            self.delay_range = delay_range
            self.human_break_every = human_break_every
            self.human_break_range = human_break_range

        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.log_event(
            "run_start",
            profile=self.profile_name,
            adaptive=adaptive,
            delay_min=self.delay_range[0],
            delay_max=self.delay_range[1],
            human_break_every=self.human_break_every,
            human_break_min=self.human_break_range[0],
            human_break_max=self.human_break_range[1],
        )

    def log_event(self, event: str, **payload: Any) -> None:
        row = {
            "event": event,
            "run_id": self.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "profile": self.profile_name,
            **payload,
        }
        with self.metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def sleep_between_requests(self, *, kind: str, label: str | int | None = None) -> float:
        delay = random.uniform(*self.delay_range) + random.uniform(0, 0.2)
        self.log_event("delay", kind=kind, label=label, seconds=round(delay, 3))
        time.sleep(delay)
        return delay

    def maybe_human_break(self, page_num: int, max_pages: int) -> float | None:
        if self.human_break_every <= 0:
            return None
        if page_num % self.human_break_every != 0 or page_num >= max_pages:
            return None
        delay = random.uniform(*self.human_break_range)
        self.log_event("human_break", page=page_num, seconds=round(delay, 3))
        time.sleep(delay)
        return delay

    def record_captcha(self, *, kind: str, label: str | int | None = None) -> str:
        next_profile = self._slower_profile()
        self.log_event("captcha_stop", kind=kind, label=label, next_profile=next_profile)
        if self.adaptive:
            self._save_state(
                {
                    "recommended_profile": next_profile,
                    "last_captcha_at": datetime.now(UTC).isoformat(),
                    "last_profile": self.profile_name,
                    "last_kind": kind,
                    "last_label": label,
                }
            )
        return next_profile

    def record_success(self, *, kind: str, label: str | int | None = None) -> None:
        self.log_event("success", kind=kind, label=label)

    def _slower_profile(self) -> str:
        if self.profile_name not in BEIKE_PROFILE_ORDER:
            return "balanced"
        index = BEIKE_PROFILE_ORDER.index(self.profile_name)
        return BEIKE_PROFILE_ORDER[min(index + 1, len(BEIKE_PROFILE_ORDER) - 1)]

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def beike_profile_names() -> tuple[str, ...]:
    return tuple(BEIKE_PROFILES)


def beike_profile_dicts() -> dict[str, dict[str, object]]:
    return {name: asdict(profile) for name, profile in BEIKE_PROFILES.items()}
