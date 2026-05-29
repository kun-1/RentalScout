"""Source-independent listing quality analysis."""

from rentalscout.analysis.wellcee_quality import (
    DEFAULT_LISTING_QUALITY_CSV,
    DEFAULT_LISTING_QUALITY_SUMMARY_JSON,
    AnalysisTier,
    WellceeQualityRow,
    analyze_wellcee_quality,
    generate_wellcee_quality_outputs,
    summarize_quality_rows,
)

ListingQualityRow = WellceeQualityRow
analyze_listing_quality = analyze_wellcee_quality
generate_listing_quality_outputs = generate_wellcee_quality_outputs

__all__ = [
    "DEFAULT_LISTING_QUALITY_CSV",
    "DEFAULT_LISTING_QUALITY_SUMMARY_JSON",
    "AnalysisTier",
    "ListingQualityRow",
    "analyze_listing_quality",
    "generate_listing_quality_outputs",
    "summarize_quality_rows",
]
