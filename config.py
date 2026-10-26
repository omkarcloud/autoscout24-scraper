"""Configuration for the AutoScout24 Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT               port the API listens on (default 8000)
    AUTOSCOUT24_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                       (default: none — direct). AutoScout24 serves most
                       networks directly; it answers 403 to some (an Indian home
                       ISP, for one). If every call fails with a 502 "blocked",
                       set a European proxy here.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

AUTOSCOUT24_PROXY = os.environ.get("AUTOSCOUT24_PROXY") or None

# The Next.js build id in AutoScout24's /_next/data/<id>/ routes. The site
# does not check it, and the scraper refreshes it from any page it reads.
AUTOSCOUT24_BUILD_ID = "as24-search-funnel_main-20261023130612"

# AutoScout24's own search-page GraphQL client credential, public in the
# site's JavaScript (used for counts, facets and the make/model matcher).
AUTOSCOUT24_GRAPHQL_AUTH = "Basic YXMyNC1zZWFyY2gtZnVubmVsOnZucmZiYkJqSTMyT2wxV2thNnVOSFJwM0VZbjRkag=="

# The headers AutoScout24's own location search sends.
AUTOSCOUT24_LOCATION_HEADERS = {"x-user": "search-funnel", "client-id": "as24-search-funnel"}


def autoscout24_proxy():
    """The proxy for a new HTTP session (None = direct)."""
    return os.environ.get("AUTOSCOUT24_PROXY") or None
