"""Schemas for source-independent rental listings."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from rentalscout.schemas.raw import SourceName


class SourceType(StrEnum):
    PLATFORM = "platform"
    UGC = "ugc"


class RentPriceUnit(StrEnum):
    MONTH = "month"
    DAY = "day"
    UNKNOWN = "unknown"


class ListingType(StrEnum):
    WHOLE_RENT = "whole_rent"
    SHARED_RENT = "shared_rent"
    SUBLET = "sublet"
    UNKNOWN = "unknown"


class LandlordType(StrEnum):
    INDIVIDUAL = "individual"
    AGENCY = "agency"
    UNKNOWN = "unknown"


class ListingAvailabilityStatus(StrEnum):
    ACTIVE = "active"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class NormalizedRentalListing(BaseModel):
    source: SourceName
    source_type: SourceType = SourceType.UGC
    source_listing_id: str | None = None
    source_url: HttpUrl
    title: str
    description: str | None = None
    rent_price: int | None = Field(default=None, ge=0)
    rent_price_unit: RentPriceUnit = RentPriceUnit.MONTH
    currency: str = "CNY"
    area_sqm: float | None = Field(default=None, gt=0)
    layout: str | None = None
    district: str | None = None
    subdistrict: str | None = None
    community_name: str | None = None
    address_text: str | None = None
    city: str | None = None
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    floor: str | None = None
    orientation: str | None = None
    available_from: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    listing_type: ListingType = ListingType.UNKNOWN
    landlord_type: LandlordType = LandlordType.UNKNOWN
    subway_info: str | None = None
    deposit: str | None = None
    features: list[str] = Field(default_factory=list)
    contact_hint: str | None = None
    image_urls: list[HttpUrl] = Field(default_factory=list)
    raw_record_id: str | None = None
    parse_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    price_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    location_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    area_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    layout_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("title")
    @classmethod
    def title_must_have_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "title cannot be empty"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def ensure_seen_range(self) -> "NormalizedRentalListing":
        if self.last_seen_at < self.first_seen_at:
            msg = "last_seen_at cannot be earlier than first_seen_at"
            raise ValueError(msg)
        return self
