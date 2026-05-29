import json

from rentalscout.crawl_control import BeikeCrawlControl


def test_beike_crawl_control_records_metrics_and_adaptive_state(tmp_path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    control = BeikeCrawlControl(
        profile_name="balanced",
        adaptive=True,
        metrics_path=metrics_path,
        state_path=state_path,
    )

    next_profile = control.record_captcha(kind="list", label=9)

    assert next_profile == "safe"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["recommended_profile"] == "safe"

    events = [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["event"] == "run_start"
    assert events[-1]["event"] == "captcha_stop"
    assert events[-1]["next_profile"] == "safe"


def test_beike_crawl_control_uses_saved_adaptive_profile(tmp_path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    state_path.write_text('{"recommended_profile": "safe"}', encoding="utf-8")

    control = BeikeCrawlControl(
        adaptive=True,
        metrics_path=metrics_path,
        state_path=state_path,
    )

    assert control.profile_name == "safe"
    assert control.delay_range == (45.0, 75.0)
