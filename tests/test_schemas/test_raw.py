from pydantic import ValidationError

from rentalscout.schemas.raw import RawPage, SourceName


def test_raw_page_accepts_raw_body() -> None:
    page = RawPage(source=SourceName.BEIKE, url="https://example.com/listing", raw_body="<html />")

    assert page.source == SourceName.BEIKE
    assert str(page.url) == "https://example.com/listing"


def test_raw_page_requires_artifact_or_error() -> None:
    try:
        RawPage(source=SourceName.WELLCEE, url="https://example.com/listing")
    except ValidationError as error:
        assert "raw_path, raw_body, or error_message" in str(error)
    else:
        raise AssertionError("expected validation error")
