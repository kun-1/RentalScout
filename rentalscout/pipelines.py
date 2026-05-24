"""Scrapy item pipelines for RentalScout."""

from __future__ import annotations

from scrapy import Spider
from scrapy.exceptions import DropItem

from rentalscout.filters import apply_phase1_filters
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.storage.sqlite import upsert_listings
from rentalscout.validation.export import (
    export_filter_candidates,
    export_validation_sample,
)


class Phase1FilterPipeline:
    """Apply phase1 filters; drop items that don't pass."""

    def __init__(self) -> None:
        self.filter_results: list = []

    def process_item(
        self,
        item: NormalizedRentalListing,
        spider: Spider,
    ) -> NormalizedRentalListing:
        result = apply_phase1_filters(item)
        self.filter_results.append(result)
        if not result.accepted:
            raise DropItem(f"Filtered: {'; '.join(result.reasons)}")
        return item

    def close_spider(self, spider: Spider) -> None:
        spider.filter_results = self.filter_results


class StoragePipeline:
    """Upsert accepted listings to SQLite."""

    def process_item(
        self,
        item: NormalizedRentalListing,
        spider: Spider,
    ) -> NormalizedRentalListing:
        upsert_listings([item])
        return item


class ExportPipeline:
    """Export filter results and accepted sample to CSVs on spider close."""

    def close_spider(self, spider: Spider) -> None:
        results = getattr(spider, "filter_results", [])
        if not results:
            return
        accepted = [r.listing for r in results if r.accepted]
        export_filter_candidates(results)
        export_validation_sample(accepted)
        spider.logger.info(
            "Export done: %d candidates, %d accepted → CSVs",
            len(results),
            len(accepted),
        )
