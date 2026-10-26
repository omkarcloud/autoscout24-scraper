"""AutoScout24 transport: plain curl_cffi with Chrome-impersonated TLS. No
browser, no cookies kept, no login. Egress per config.autoscout24_proxy()
(knob AUTOSCOUT24_EXIT): the pod's own IP passed every surface below in the
2026-10-24 pod probe (table in config's "--- autoscout24 ---" block). A
retryable failure drops the thread's session, so the retry rides a fresh
connection (and a fresh exit when a proxy tier is set).

Upstream surfaces (all on www.autoscout24.com unless noted):

  * SEARCH   GET /_next/data/<buildId>/lst[/<make>/<model>].json?<query>
             The Next.js data route of the /lst page: the same props the
             page renders, ~150 KB for 20 results, `taxonomy` null. The
             build id is not checked by the site; a 404 there falls back to
             the server-rendered /lst page (which also refreshes the id).
  * FILTERS  GET /lst?atype=<type>&size=1 — the only place the filter
             taxonomy (makes, body types, equipment, colours...) ships.
  * LISTING  GET /_next/data/<buildId>/details/<guid>.json?slug=<guid>,
             falling back to the HTML /offers/<guid>. An unknown or expired
             GUID answers a real HTTP 404 on both.
  * DEALER   GET /dealerinfo/<slug-or-customer-id>[/list?...] — the dealer
             Next app; profile, 10 newest reviews and 20 listings in its
             __NEXT_DATA__. Unknown dealers answer HTTP 404.
  * REVIEWS  POST /api/dealer-detail/fetch-reviews {"customerId", "skip"}
             -> a JSON list of 10 (the page's own "show more" call).
  * MODELS   GET /as24-home/api/taxonomy/<cars|bikes>/makes/<id>/models
  * GRAPHQL  POST /listing-search-api/graphql (Basic token in config) —
             result counts, facet counters, the free-text model search.
  * PLACES   GET https://location-api.as24-location-services.aws.as24.tech/
             autocomplete/<CC>?query=..[&type=POSTCODE]
  * LOCALIZED by-link only: the link's own market host normalizes a
             localized model slug (/lst/bmw/3er-(alle) on .de); .com would
             silently drop it.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  AutoScout24UpstreamError  transport failure / 5xx / malformed page  — retryable
  AutoScout24Blocked        401 / 403 / 429 / non-JSON on a JSON route — retryable
  AutoScout24BadRequest     upstream 400                               — never retried
  AutoScout24NotFound       HTTP 404 / the site's "Error Pages" page    — never retried
The site's refusal page and its 404 page are the same "Error Pages"
template; only the status tells them apart (403 = refused, 404 = gone).
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

# Allow direct execution (python autoscout24/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from autoscout24.parsers import next_data, page_title
from autoscout24.refs import SITE

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40     # /lst pages run 0.5-0.9 MB, dealer pages ~0.3 MB
JSON_TIMEOUT = 30
LOCATION_API = "https://location-api.as24-location-services.aws.as24.tech/autocomplete"
GRAPHQL_URL = SITE + "/listing-search-api/graphql"
REVIEWS_URL = SITE + "/api/dealer-detail/fetch-reviews"
GRAPHQL_LOCALE = "en_GB"   # the .com marketplace's culture (AS_en_GB)

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}
DATA_HEADERS = {
    "accept": "*/*",
    "x-nextjs-data": "1",
    "referer": SITE + "/lst",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}
API_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": SITE,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

_SEARCH_BUILD_RE = re.compile(r"^as24-search-funnel_")


class AutoScout24UpstreamError(UpstreamError):
    """Transport failure, 5xx or a page without the expected data — retryable."""


class AutoScout24Blocked(AutoScout24UpstreamError, Blocked):
    """401 / 403 / 429, or a non-JSON body on a JSON route — retryable."""


class AutoScout24BadRequest(BadRequest):
    """Upstream 400 — never retried."""


class AutoScout24NotFound(NotFound):
    """The listing / dealer / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per cheroot worker thread (a curl handle must never be
# shared across threads); keep-alive within the thread. The session's
# Accept-Language follows its exit (egress.accept_language).

_local = threading.local()
_build = {"id": config.AUTOSCOUT24_BUILD_ID}


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        proxy = config.autoscout24_proxy()
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers.update({"accept-language": egress.accept_language(proxy)})
        _local.session = sess
    return sess


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection (or a
    refused exit) dies with it."""
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn):
    """Run fn() under the shared retry policy (AutoScout24UpstreamError and
    AutoScout24Blocked only; NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except AutoScout24UpstreamError as e:
            last = e
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def build_id():
    return _build["id"]


def _note_build_id(data):
    """Keep the newest search-funnel build id seen on a rendered page."""
    bid = (data or {}).get("buildId")
    if isinstance(bid, str) and _SEARCH_BUILD_RE.match(bid):
        _build["id"] = bid


# ---- HTTP plumbing ---------------------------------------------------------------

def _request(method, url, label, headers, timeout, **kw):
    try:
        return _session().request(method, url, headers=headers, timeout=timeout, **kw)
    except Exception as e:
        raise AutoScout24UpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")


def _classify(resp, label):
    """Map an HTTP status to the error taxonomy; return the body text."""
    status = resp.status_code
    if status == 404:
        raise AutoScout24NotFound(f"{label} not found")
    if status == 400:
        raise AutoScout24BadRequest(f"HTTP 400 for {label}: {resp.text[:200]}")
    if status in (401, 403, 429):
        raise AutoScout24Blocked(f"HTTP {status} for {label}")
    if status != 200:
        raise AutoScout24UpstreamError(f"HTTP {status} for {label}")
    return resp.text


def _json(resp, label):
    try:
        return resp.json()
    except Exception:
        raise AutoScout24Blocked(f"non-JSON body for {label}: {resp.text[:120]!r}")


def _with_query(url, params):
    query = urlencode(list(params or []), doseq=True)
    return f"{url}?{query}" if query else url


def _page_props(url, label, *, not_found=None):
    """GET a server-rendered page and return its __NEXT_DATA__ (whole)."""
    resp = _request("GET", url, label, PAGE_HEADERS, PAGE_TIMEOUT)
    if resp.status_code == 404 and not_found:
        raise AutoScout24NotFound(not_found)
    text = _classify(resp, label)
    data = next_data(text)
    if data is None:
        if page_title(text) == "Error Pages":
            raise AutoScout24NotFound(not_found or f"{label} not found")
        raise AutoScout24Blocked(f"{label}: no page data in a {len(text)}-byte page")
    _note_build_id(data)
    return data


def _data_route(path, params, label):
    """GET /_next/data/<build id><path>.json -> the response object (status
    unchecked so the caller decides what a 404 means)."""
    url = _with_query(f"{SITE}/_next/data/{_build['id']}{path}.json", params)
    return _request("GET", url, label, DATA_HEADERS, JSON_TIMEOUT)


# ---- search --------------------------------------------------------------------------

def _search_html(path, params, label):
    data = _page_props(_with_query(SITE + path, params), label,
                       not_found="no AutoScout24 search page at that link")
    props = (data.get("props") or {}).get("pageProps") or {}
    if data.get("page") not in ("/lst", "/lst/[...slug]") or "listings" not in props:
        raise AutoScout24BadRequest("that link is not an AutoScout24 search results page")
    return props


def fetch_search(path="/lst", params=()):
    """The /lst page props for a search: `listings`, `numberOfResults`,
    `numberOfPages`, `pageQuery` (the query as the server normalized it)."""
    label = f"search {path}"

    def once():
        resp = _data_route(path, params, label)
        if resp.status_code == 404:
            # A build id the site started refusing, or a path the data
            # route does not serve (/lst-moto): read the page itself.
            return _search_html(path, params, label)
        _classify(resp, label)
        props = (_json(resp, label) or {}).get("pageProps") or {}
        redirect = props.get("__N_REDIRECT")
        if isinstance(redirect, str):
            return _search_html(redirect.split("?")[0], _query_pairs(redirect), label)
        if "listings" not in props:
            raise AutoScout24UpstreamError(f"{label}: no listings in the page data")
        return props
    return _retrying(once)


def _query_pairs(url):
    from urllib.parse import parse_qsl, urlparse
    return parse_qsl(urlparse(url).query)


def fetch_search_page(vehicle_type_code):
    """The rendered /lst page for one vehicle type, size 1 (its props carry
    the filter taxonomy; the data route sends taxonomy: null)."""
    label = f"filter page atype={vehicle_type_code}"

    def once():
        data = _page_props(_with_query(SITE + "/lst", [("atype", vehicle_type_code), ("size", "1")]), label)
        props = (data.get("props") or {}).get("pageProps") or {}
        if not isinstance(props.get("taxonomy"), dict):
            raise AutoScout24UpstreamError(f"{label}: no taxonomy in the page data")
        return props
    return _retrying(once)


def fetch_localized_search(tld, path, params):
    """by-link only: the page props of a /lst link on its own market host
    (www.autoscout24.<tld>), read for its `pageQuery` — the host resolves its
    own localized make / model slugs into ids."""
    host = f"https://www.autoscout24.{tld}"
    label = f"search link on autoscout24.{tld}"

    def once():
        url = _with_query(f"{host}/_next/data/{_build['id']}{path}.json", params)
        resp = _request("GET", url, label, DATA_HEADERS, JSON_TIMEOUT)
        if resp.status_code == 200:
            try:
                props = (resp.json() or {}).get("pageProps") or {}
            except Exception:
                props = {}
            if isinstance(props.get("pageQuery"), dict):
                return props
        elif resp.status_code in (401, 403, 429):
            raise AutoScout24Blocked(f"HTTP {resp.status_code} for {label}")
        data = _page_props(_with_query(host + path, params), label,
                           not_found="no AutoScout24 search page at that link")
        props = (data.get("props") or {}).get("pageProps") or {}
        if not isinstance(props.get("pageQuery"), dict):
            raise AutoScout24BadRequest("that link is not an AutoScout24 search results page")
        return props
    return _retrying(once)


# ---- listing ---------------------------------------------------------------------------

def fetch_listing(guid):
    """The detail page props of one listing (`listingDetails` inside)."""
    label = f"listing {guid}"
    gone = f"listing {guid} not found (sold, expired or never existed)"

    def once():
        resp = _data_route(f"/details/{guid}", [("slug", guid)], label)
        if resp.status_code == 200:
            props = (_json(resp, label) or {}).get("pageProps") or {}
            if props.get("__N_REDIRECT"):
                raise AutoScout24NotFound(gone)
            if isinstance(props.get("listingDetails"), dict):
                return props
        elif resp.status_code in (401, 403, 429):
            raise AutoScout24Blocked(f"HTTP {resp.status_code} for {label}")
        elif resp.status_code >= 500:
            raise AutoScout24UpstreamError(f"HTTP {resp.status_code} for {label}")
        # 404 or an odd payload on the data route: the page decides (its
        # 404 is the authoritative "gone").
        data = _page_props(f"{SITE}/offers/{guid}", label, not_found=gone)
        props = (data.get("props") or {}).get("pageProps") or {}
        if not isinstance(props.get("listingDetails"), dict):
            raise AutoScout24UpstreamError(f"{label}: no listing data in the page")
        return props
    return _retrying(once)


# ---- dealers ----------------------------------------------------------------------------

def fetch_dealer(token, sub="", params=()):
    """A dealer page's props: `dealerInfoPage`, `listings`, `numberOfResults`.
    `token` is the slug or the numeric customer id; `sub` is "" (home: 20
    listings + 10 reviews) or "list" (the filtered inventory)."""
    path = f"/dealerinfo/{token}" + (f"/{sub}" if sub else "")
    label = f"dealer {token}"

    def once():
        data = _page_props(_with_query(SITE + path, params), label,
                           not_found=f"dealer {token} not found")
        props = (data.get("props") or {}).get("pageProps") or {}
        if not isinstance(props.get("dealerInfoPage"), dict):
            raise AutoScout24UpstreamError(f"{label}: no dealer data in the page")
        return props
    return _retrying(once)


def fetch_reviews(customer_id, skip):
    """POST fetch-reviews -> a list of up to 10 reviews. The site clamps
    `skip` below 10 to 10 (the first ten ship with the page), so callers
    only ask for skip >= 10. Past the end -> []."""
    label = f"dealer {customer_id} reviews"

    def once():
        headers = {**API_HEADERS, "referer": f"{SITE}/dealerinfo/{customer_id}/ratings"}
        resp = _request("POST", REVIEWS_URL, label, headers, JSON_TIMEOUT,
                        data=json.dumps({"customerId": int(customer_id), "skip": int(skip)}))
        _classify(resp, label)
        if not resp.content.strip():
            return []      # the site's answer for an unknown customer id
        payload = _json(resp, label)
        if not isinstance(payload, list):
            raise AutoScout24UpstreamError(f"{label}: unexpected payload {str(payload)[:120]}")
        return payload
    return _retrying(once)


# ---- taxonomy / counts / places ----------------------------------------------------------

def fetch_models(catalog, make_id):
    """The model catalog of one make: {"models": {"model": {"values": []},
    "modelGroup": {...}, "modelLine": {...}}}."""
    label = f"models of make {make_id}"

    def once():
        url = f"{SITE}/as24-home/api/taxonomy/{catalog}/makes/{int(make_id)}/models"
        resp = _request("GET", url, label, API_HEADERS, JSON_TIMEOUT)
        _classify(resp, label)
        payload = _json(resp, label)
        if not isinstance(payload, dict):
            raise AutoScout24UpstreamError(f"{label}: unexpected payload")
        return payload
    return _retrying(once)


def graphql(query, variables, label="graphql"):
    """POST the search funnel's GraphQL API -> `data`. GraphQL errors mean
    our query no longer matches the schema: an upstream error, not a 400."""
    def once():
        headers = {**API_HEADERS, "authorization": config.AUTOSCOUT24_GRAPHQL_AUTH,
                   "culture": GRAPHQL_LOCALE, "x-culture": GRAPHQL_LOCALE.replace("_", "-"),
                   "referer": SITE + "/lst"}
        resp = _request("POST", GRAPHQL_URL, label, headers, JSON_TIMEOUT,
                        data=json.dumps({"query": query, "variables": variables}))
        _classify(resp, label)
        payload = _json(resp, label)
        if not isinstance(payload, dict):
            raise AutoScout24UpstreamError(f"{label}: unexpected payload")
        if payload.get("errors") and not payload.get("data"):
            first = (payload["errors"][0] or {}).get("message", "")
            raise AutoScout24UpstreamError(f"{label}: {first[:200]}")
        return payload.get("data") or {}
    return _retrying(once)


def fetch_locations(country_iso, query, postcode=False):
    """Location autocomplete for one market -> a list of places."""
    label = f"location search {country_iso}"

    def once():
        params = [("query", query)] + ([("type", "POSTCODE")] if postcode else [])
        headers = {**API_HEADERS, **config.AUTOSCOUT24_LOCATION_HEADERS, "referer": SITE + "/"}
        resp = _request("GET", _with_query(f"{LOCATION_API}/{country_iso}", params), label,
                        headers, JSON_TIMEOUT)
        _classify(resp, label)
        if not resp.content.strip():
            return []
        payload = _json(resp, label)
        return payload if isinstance(payload, list) else []
    return _retrying(once)
