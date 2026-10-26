"""Cache TTL per /autoscout24/* endpoint (cache.py, keyed on the validated
params). api.py caches inside, tofler-style: listings/details and
listings/similar share ONE cached listing parse, and dealers/details,
dealers/listings (page 1, no filters) and dealers/reviews (page 1) share ONE
cached dealer page parse, so a client hitting all of them pays one fetch.
"""
from datetime import timedelta

# Search results move all day (dealers list and re-price constantly).
SEARCH_CACHE = timedelta(minutes=30)
# One listing: price and status change at most a few times a week.
LISTING_CACHE = timedelta(hours=3)
# Similar listings are a search: same churn as search.
SIMILAR_CACHE = timedelta(hours=1)
# Counts and facet counters drift slowly at market scale.
COUNT_CACHE = timedelta(hours=1)
# The dealer page (profile, newest reviews, first 20 listings).
DEALER_CACHE = timedelta(hours=6)
# A dealer's filtered / later inventory pages.
DEALER_LISTINGS_CACHE = timedelta(hours=1)
# Older review pages only grow at the front.
DEALER_REVIEWS_CACHE = timedelta(hours=12)
# The filter taxonomy of a vehicle type (makes, body types, equipment).
TAXONOMY_CACHE = timedelta(hours=24)
# A make's model catalog: models are added a few times a year.
MODEL_CATALOG_CACHE = timedelta(days=7)
# taxonomy/makes and taxonomy/models carry live listing counts.
MAKES_CACHE = timedelta(hours=6)
MODELS_CACHE = timedelta(hours=6)
# The free-text make / model matcher.
TAXONOMY_SEARCH_CACHE = timedelta(hours=24)
# Places and postcodes do not move.
LOCATIONS_CACHE = timedelta(days=30)
