"""Reference resolvers + the code tables the /autoscout24/* schemas need.

ONE param per input (tripadvisor QueryOrIdField convention):

  * `listing`  a bare listing GUID (2949f4f3-5892-47f8-be2d-dd2a4eaa2808) OR
               any AutoScout24 offer link on any market host: the GUID is
               the last path segment (/offers/<slug>-<guid> on .com,
               /angebote/ .de/.at, /annunci/ .it, /offres/ .fr/.lu,
               /aanbod/ .nl, /anuncios/ .es, /oferta/ .pl). The slug is
               ignored by the site: /offers/<guid> alone serves the page.
  * `dealer`   a dealer slug (autohaus-heinrich-gmbh), the numeric customer
               id (5623) OR any dealer page link (/dealerinfo/ .com/.pl,
               /haendler/ .de/.at, /concessionari/ .it, /garages/ .fr,
               /autobedrijven/ .nl, /profesionales/ .es, /professional/
               .lu). www.autoscout24.com/dealerinfo/<slug-or-id> serves the
               same page for both forms (checked 2026-10-24).
  * `link`     an AutoScout24 search-results link (/lst...) on any market
               host, for /autoscout24/listings/by-link.

autoscout24.ch is a different platform (no /lst, no dealerinfo) and is
rejected. Market hosts and their URL segments were read off each host's
own /lst page on 2026-10-24.

The code tables are the site's own query values (the search funnel bundle
5007-36dd8ab8d9ad8753.js maps every filter to its query key, and the /lst
page's __NEXT_DATA__ taxonomy lists the values; both read 2026-10-24).
"""
import re
from urllib.parse import parse_qsl, urlparse

SITE = "https://www.autoscout24.com"
HOST = "www.autoscout24.com"

# Market hosts that run the same platform (the ".ch" site does not).
MARKET_TLDS = ("com", "de", "at", "it", "fr", "nl", "es", "be", "lu", "pl")
# A /lst link without `cy` searches the host's own market.
TLD_COUNTRY = {"de": "D", "at": "A", "it": "I", "fr": "F", "nl": "NL", "es": "E", "be": "B", "lu": "L"}

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_TRAILING_GUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$", re.I)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,150}$")
CUSTOMER_ID_RE = re.compile(r"^[0-9]{1,12}$")
DEALER_SEGMENTS = ("dealerinfo", "haendler", "concessionari", "garages", "autobedrijven",
                   "profesionales", "professional")
_DEALER_PATH_RE = re.compile(r"^/(?:[a-z]{2}/)?(?:%s)/([^/?#]+)" % "|".join(DEALER_SEGMENTS), re.I)


def _url_of(value):
    """A pasted link as an absolute URL, or None when it is not one."""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.lower().startswith(("www.autoscout24.", "autoscout24.")):
        return "https://" + value
    return None


def market_tld(url):
    """The market TLD of an AutoScout24 link ("com", "de", ...), or raise."""
    host = (urlparse(url).hostname or "").lower()
    labels = host.split(".")
    if len(labels) >= 2 and labels[-2] == "autoscout24" and labels[-1] in MARKET_TLDS:
        return labels[-1]
    if len(labels) >= 2 and labels[-2] == "autoscout24":
        raise ValueError(f"autoscout24.{labels[-1]} is a different platform; use a link from "
                         "autoscout24.com, .de, .at, .it, .fr, .nl, .es, .be, .lu or .pl.")
    raise ValueError("Must be an AutoScout24 link.")


def resolve_listing(value):
    """Bare listing GUID or any AutoScout24 offer link -> the GUID (lower case)."""
    value = (value or "").strip()
    if GUID_RE.match(value):
        return value.lower()
    url = _url_of(value)
    if url:
        market_tld(url)
        path = urlparse(url).path
        match = _TRAILING_GUID_RE.search(path)
        if match:
            return match.group(1).lower()
        raise ValueError("Must be an AutoScout24 offer link "
                         "(https://www.autoscout24.com/offers/<slug>-<listing id>).")
    raise ValueError("Must be a listing id (2949f4f3-5892-47f8-be2d-dd2a4eaa2808) "
                     "or an AutoScout24 offer link.")


def resolve_dealer(value):
    """Dealer slug, numeric customer id or any dealer page link -> the
    path token www.autoscout24.com/dealerinfo/<token> accepts."""
    value = (value or "").strip()
    url = _url_of(value)
    if url:
        market_tld(url)
        match = _DEALER_PATH_RE.match(urlparse(url).path)
        if match:
            token = match.group(1).lower()
            if SLUG_RE.match(token):
                return token
        raise ValueError("Must be an AutoScout24 dealer page link "
                         "(https://www.autoscout24.com/dealerinfo/<dealer>).")
    low = value.lower()
    if CUSTOMER_ID_RE.match(low) or SLUG_RE.match(low):
        return low
    raise ValueError("Must be a dealer slug (autohaus-heinrich-gmbh), a numeric customer id "
                     "or an AutoScout24 dealer page link.")


def resolve_search_link(value):
    """An AutoScout24 /lst search link on any market host ->
    {"tld", "path", "params"} with the path relative to the host root (a
    "/nl/" or "/fr/" language prefix kept) and the query as a list of pairs."""
    value = (value or "").strip()
    url = _url_of(value)
    if not url:
        raise ValueError("Must be an AutoScout24 search results link "
                         "(https://www.autoscout24.com/lst?...).")
    tld = market_tld(url)
    parsed = urlparse(url)
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    if not re.match(r"^/(?:[a-z]{2}/)?lst(?:-[a-z]+)?(?:/|$)", path):
        raise ValueError("Must be an AutoScout24 search results link (the path starts with /lst).")
    return {"tld": tld, "path": path, "params": parse_qsl(parsed.query, keep_blank_values=False)}


def listing_link(guid):
    return f"{SITE}/offers/{guid}"


def dealer_link(token):
    return f"{SITE}/dealerinfo/{token}" if token else None


def absolute(path):
    """A site-relative path ("/offers/...") as a www.autoscout24.com link."""
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    return SITE + (path if path.startswith("/") else "/" + path)


def dealer_token_of(link):
    """The dealer slug inside a dealer page link, or None."""
    if not link:
        return None
    match = _DEALER_PATH_RE.match(urlparse(link).path or "")
    return match.group(1).lower() if match else None


# ---- code tables -------------------------------------------------------------

# Public value -> the site's `atype`. Trucks, boats and the other article
# types in the bundle are not served on these hosts (they coerce to cars).
VEHICLE_TYPES = {"car": "C", "motorbike": "B", "caravan": "N", "transporter": "X", "trailer": "L"}
VEHICLE_TYPE_OF_CODE = {code: name for name, code in VEHICLE_TYPES.items()}
# /as24-home/api/taxonomy/<catalog>/makes/<id>/models: only "cars" and
# "bikes" are real catalogs (any other name falls back to cars); transporter
# models are car models, caravans and trailers have none (2026-10-24).
MODEL_CATALOG = {"C": "cars", "X": "cars", "B": "bikes"}

# ISO 3166 -> the site's `cy`; "EU" = all eight markets at once.
COUNTRIES = {"AT": "A", "BE": "B", "DE": "D", "ES": "E", "FR": "F", "IT": "I", "LU": "L", "NL": "NL"}
EU = "EU"
EU_CODE = "A,B,D,E,F,I,L,NL"
COUNTRY_OF_CODE = {code: iso for iso, code in COUNTRIES.items()}
# The free-text model search takes the market as an ISO code.
MARKETPLACE_OF_CODE = {code: iso for iso, code in COUNTRIES.items()}

FUELS = {"gasoline": "B", "diesel": "D", "electric": "E", "electric-gasoline": "2",
         "electric-diesel": "3", "lpg": "L", "cng": "C", "hydrogen": "H", "ethanol": "M",
         "two-stroke": "T", "other": "O"}
TRANSMISSIONS = {"automatic": "A", "manual": "M", "semi-automatic": "S"}
DRIVETRAINS = {"4x4": "4", "front": "F", "rear": "R"}
CONDITIONS = {"new": "N", "used": "U", "employee-car": "J", "classic": "O", "demonstration": "D",
              "pre-registered": "S"}
OFFER_TYPE_LABELS = {"N": "new", "U": "used", "J": "employee_car", "O": "classic",
                     "D": "demonstration", "S": "pre_registered"}
SELLER_TYPES = {"dealer": "D", "private": "P"}
UPHOLSTERY = {"alcantara": "AL", "cloth": "CL", "full-leather": "FL", "part-leather": "PL",
              "velour": "VL", "other": "OT"}
CYLINDERS = {"3": "3", "4": "4", "6": "6", "8": "8", "10plus": "10plus"}
# `damaged_listing`: the site hides damaged vehicles unless asked.
DAMAGED = {"exclude": "exclude", "include": "include", "only": "damaged-only"}
POWER_UNITS = {"kw": "kw", "hp": "hp"}

# sort public value -> the site's `sort` key; `order` -> `desc`.
SORTS = {"relevance": "standard", "price": "price", "newest": "age", "mileage": "mileage",
         "first-registration": "year", "power": "power", "distance": "distance", "make": "make",
         "finance-rate": "financerate", "leasing-rate": "leasing_rate"}
ORDERS = {"asc": "0", "desc": "1"}
DEALER_SORTS = {"relevance": "standard", "price": "price", "newest": "age", "mileage": "mileage",
                "first-registration": "year", "power": "power"}

# Search results per page the site serves (any size works; the site caps
# every query at 4,000 reachable results: 200 pages of 20, 20 of 200).
MAX_REACHABLE_RESULTS = 4000
