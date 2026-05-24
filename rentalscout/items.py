from __future__ import annotations

from rentalscout.schemas.normalized import NormalizedRentalListing

# Reuse NormalizedRentalListing directly as the "item"
# No custom Scrapy Item class needed
BeikeItem = NormalizedRentalListing
WellceeItem = NormalizedRentalListing
