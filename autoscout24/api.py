"""The /autoscout24/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs). Caching lives here, tofler-style:

  * listings/details and listings/similar slice ONE cached listing parse
    (autoscout24.listing, keyed on the GUID);
  * dealers/details, dealers/listings page 1 without filters and
    dealers/reviews page 1 slice ONE cached dealer page parse
    (autoscout24.dealer): the home page carries the profile, the first 20
    listings and the 10 newest reviews;
  * make / model names resolve against the cached filter taxonomy of the
    vehicle type and the cached model catalog of the make, so a search by
    name costs no extra upstream call once those are warm.
"""
import math
import re
from urllib.parse import urlencode

from cache import cached_call
from autoscout24 import cache_config as ttl
from autoscout24 import fetch, parsers, refs
from autoscout24.schemas import SearchFiltersSchema

SEARCH_PAGE_SIZE = 20       # the site's default page size
DEALER_PAGE_SIZE = 20       # dealer inventory pages
REVIEWS_PAGE_SIZE = 10      # reviews per page (page load and fetch-reviews)

# The site's server-added query keys, dropped when a link's normalized
# query is replayed (they are per-request noise, not filters).
_NOISE_KEYS = {"query_id", "tier_rotation", "show_nfm", "pricetype", "page", "size", "source",
               "search_id", "ipc", "ipl", "position"}

_USAGE_STATES = {"U": "used", "N": "new", "A": "damaged"}


# ---- shared taxonomy ----------------------------------------------------------------

def _taxonomy_record(vehicle_type):
    taxonomy = fetch.fetch_search_page(vehicle_type).get("taxonomy") or {}
    return {"makes": parsers.parse_makes(taxonomy), "filters": parsers.parse_filters(taxonomy)}


def _taxonomy(vehicle_type):
    return cached_call("autoscout24.taxonomy", {"vehicle_type": vehicle_type}, _taxonomy_record,
                       ttl.TAXONOMY_CACHE)


def _catalog_record(vehicle_type, make_id):
    catalog = refs.MODEL_CATALOG.get(vehicle_type)
    if not catalog:      # caravans and trailers have no model catalog on the site
        return {"models": [], "model_groups": [], "model_lines": []}
    return parsers.parse_models(fetch.fetch_models(catalog, make_id))


def _catalog(vehicle_type, make_id):
    return cached_call("autoscout24.model_catalog", {"vehicle_type": vehicle_type, "make_id": make_id},
                       _catalog_record, ttl.MODEL_CATALOG_CACHE)


def _norm(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _type_name(code):
    return refs.VEHICLE_TYPE_OF_CODE.get(code)


def resolve_make(vehicle_type, value):
    """A make id or name -> {"id", "name"} (ValueError -> 400 when unknown)."""
    if value is None:
        return None
    makes = _taxonomy(vehicle_type)["makes"]
    if value.isdigit():
        make_id = int(value)
        name = next((m["name"] for m in makes if m["id"] == make_id), None)
        return {"id": make_id, "name": name}
    wanted = _norm(value)
    for make in makes:
        if _norm(make["name"]) == wanted:
            return {"id": make["id"], "name": make["name"]}
    raise ValueError(f"make: unknown make '{value}' for vehicle_type={_type_name(vehicle_type)} "
                     "(see /autoscout24/taxonomy/makes).")


def resolve_model(vehicle_type, make, value):
    """A model id or name -> {"kind": model | model_group | model_line, "id", "name"}."""
    if value is None or make is None:
        return None
    catalog = _catalog(vehicle_type, make["id"])
    if value.isdigit():
        # A model id of this make first; many model NAMES are digits too
        # (Porsche 911, Peugeot 208, BMW 320), so a name match comes next.
        model_id = int(value)
        name = next((m["name"] for m in catalog["models"] if m["id"] == model_id), None)
        if name is not None:
            return {"kind": "model", "id": model_id, "name": name}
    wanted = _norm(value)
    for kind, entries in (("model", catalog["models"]), ("model_group", catalog["model_groups"]),
                          ("model_line", catalog["model_lines"])):
        for entry in entries:
            if _norm(entry["name"]) == wanted:
                return {"kind": kind, "id": entry["id"], "name": entry["name"]}
    if value.isdigit() and not catalog["models"]:
        # no catalog to check against (caravans, trailers): trust the id
        return {"kind": "model", "id": int(value), "name": None}
    raise ValueError(f"model: unknown model '{value}' for {make.get('name') or make['id']} "
                     "(see /autoscout24/taxonomy/models).")


def _make_model_params(make, model, variant):
    """The site's make / model filter: `mmmv` = make|model|model line|version,
    or `cat` = ma<make>gr<group>[_version] for a model group."""
    if not make:
        return []
    version = (variant or "").replace(",", " ").strip()
    if model and model["kind"] == "model_group":
        return [("cat", f"ma{make['id']}gr{model['id']}" + (f"_{version}" if version else ""))]
    model_id = model["id"] if model and model["kind"] == "model" else ""
    line_id = model["id"] if model and model["kind"] == "model_line" else ""
    return [("mmmv", f"{make['id']}|{model_id}|{line_id}|{version}")]


def _join(values):
    return ",".join(str(v) for v in values) if values else None


def _filter_params(filters, make, model):
    """The validated search filters -> the site's /lst query pairs."""
    f = filters
    pairs = [("atype", f["vehicle_type"]), ("cy", f["country"])]
    pairs += _make_model_params(make, model, f.get("variant"))
    if f.get("power_from") or f.get("power_to"):
        pairs.append(("powertype", f.get("power_unit") or "kw"))
    damaged = f.get("damaged")
    if damaged == "include":
        pairs += [("ustate", "A,N,U"), ("damaged_listing", "include")]
    elif damaged == "damaged-only":
        pairs += [("ustate", "A"), ("damaged_listing", "damaged-only")]
    mapping = (
        ("keyword", "kwd"), ("price_from", "pricefrom"), ("price_to", "priceto"),
        ("year_from", "fregfrom"), ("year_to", "fregto"), ("mileage_from", "kmfrom"), ("mileage_to", "kmto"),
        ("power_from", "powerfrom"), ("power_to", "powerto"), ("seller_type", "custtype"),
        ("doors_from", "doorfrom"), ("doors_to", "doorto"), ("seats_from", "seatsfrom"), ("seats_to", "seatsto"),
        ("previous_owners", "prevownersid"), ("emission_class", "emclass"), ("emission_sticker", "ensticker"),
        ("online_since", "adage"), ("electric_range_from", "erfrom"), ("electric_range_to", "erto"),
        ("engine_size_from", "ccmfrom"), ("engine_size_to", "ccmto"), ("location", "zip"), ("radius", "zipr"),
    )
    for key, site_key in mapping:
        if f.get(key) is not None:
            pairs.append((site_key, str(f[key])))
    for key, site_key in (("fuel", "fuel"), ("transmission", "gear"), ("drivetrain", "dtrain"),
                          ("body_type", "body"), ("condition", "offer"), ("color", "bcol"),
                          ("interior_color", "icol"), ("upholstery", "uph"), ("equipment", "eq"),
                          ("cylinders", "cylinders")):
        joined = _join(f.get(key))
        if joined:
            pairs.append((site_key, joined))
    if f.get("is_vat_deductible"):
        pairs.append(("vatded", "true"))
    if f.get("is_super_deal"):
        pairs.append(("superdeal", "true"))
    return pairs


def _search_link(path, pairs):
    return f"{refs.SITE}{path}?{urlencode(pairs)}"


def _country_iso(code):
    return refs.EU if code == refs.EU_CODE else refs.COUNTRY_OF_CODE.get(code)


def _filters_echo(filters, make, model):
    return {
        "vehicle_type": _type_name(filters["vehicle_type"]),
        "country": _country_iso(filters["country"]),
        "make": make,
        "model": model,
    }


def _search_pagination(parsed, page, size):
    total, pages = parsed["total_count"], parsed["total_pages"]
    if not parsed["results"] and page > 1 and not total:
        # past the end (or the 4,000 cap): the site reports 0 / 0 there
        return {"page": page, "items_per_page": size, "has_next": False, "total_pages": None, "total_count": None}
    # the site reports 1 page for 0 results; 0 / 0 reads as what it is
    return {"page": page, "items_per_page": size, "total_pages": (pages or 0) if total else 0,
            "total_count": total or 0}


def _reachable(total):
    return min(total, refs.MAX_REACHABLE_RESULTS) if isinstance(total, int) else None


# ---- listings/search -----------------------------------------------------------------------

_FILTER_KEYS = tuple(SearchFiltersSchema._declared_fields)


def _search(**data):
    filters = {k: data.get(k) for k in _FILTER_KEYS}
    make = resolve_make(filters["vehicle_type"], filters.get("make"))
    model = resolve_model(filters["vehicle_type"], make, filters.get("model"))
    pairs = _filter_params(filters, make, model)
    pairs += [("sort", data["sort"]), ("desc", data["order"])]
    page, size = data["page"], data["page_size"]
    props = fetch.fetch_search("/lst", pairs + [("page", str(page)), ("size", str(size))])
    parsed = parsers.parse_search(props)
    return {
        "search_link": _search_link("/lst", pairs + [("page", str(page))]),
        "filters": _filters_echo(filters, make, model),
        "reachable_count": _reachable(parsed["total_count"]),
        "results": parsed["results"],
        "pagination": _search_pagination(parsed, page, size),
    }


def listings_search(**data):
    return cached_call("autoscout24.search", data, _search, ttl.SEARCH_CACHE)


# ---- listings/by-link ----------------------------------------------------------------------

def _by_link(link, page, page_size):
    tld, path = link["tld"], link["path"]
    params = {}
    for key, value in link["params"]:
        params[key] = value           # a repeated key: the last one wins, like the site
    link_page = int(params["page"]) if str(params.get("page", "")).isdigit() else 1
    link_size = int(params["size"]) if str(params.get("size", "")).isdigit() else SEARCH_PAGE_SIZE
    page = page or max(link_page, 1)
    size = min(page_size or link_size or SEARCH_PAGE_SIZE, 200)
    has_slug = bool(re.match(r"^/(?:[a-z]{2}/)?lst/.+", path))
    if tld != "com" and has_slug:
        # A localized model slug: let its own host turn it into ids first.
        normalized = fetch.fetch_localized_search(tld, path, list(params.items())).get("pageQuery") or {}
        params = {str(k): str(v) for k, v in normalized.items() if v is not None}
        path = "/lst"
    path = re.sub(r"^/[a-z]{2}(?=/lst)", "", path)   # .be's /nl/ and /fr/ prefixes
    if "cy" not in params and tld in refs.TLD_COUNTRY:
        params["cy"] = refs.TLD_COUNTRY[tld]
    pairs = [(k, v) for k, v in params.items() if k not in _NOISE_KEYS]
    props = fetch.fetch_search(path, pairs + [("page", str(page)), ("size", str(size))])
    parsed = parsers.parse_search(props)
    query = {k: v for k, v in parsed["query"].items() if k not in _NOISE_KEYS}
    return {
        "search_link": _search_link(path, pairs + [("page", str(page))]),
        "query": query,
        "reachable_count": _reachable(parsed["total_count"]),
        "results": parsed["results"],
        "pagination": _search_pagination(parsed, page, size),
    }


def listings_by_link(**data):
    return cached_call("autoscout24.by_link", data, _by_link, ttl.SEARCH_CACHE)


# ---- listings/details + listings/similar (one cached listing parse) --------------------------

def _listing_record(listing):
    return parsers.parse_listing(fetch.fetch_listing(listing))


def _listing(listing):
    return cached_call("autoscout24.listing", {"listing": listing}, _listing_record, ttl.LISTING_CACHE)


def listing_details(listing):
    return _listing(listing)


def _similar(listing, limit):
    record = _listing(listing)
    vehicle = record.get("vehicle") or {}
    type_code = refs.VEHICLE_TYPES.get(vehicle.get("type") or "car", "C")
    country = refs.COUNTRIES.get((record.get("location") or {}).get("country_code") or "", "D")
    pairs = [("atype", type_code), ("cy", country)]
    criteria = {"vehicle_type": _type_name(type_code), "country": refs.COUNTRY_OF_CODE.get(country),
                "make_id": vehicle.get("make_id"), "model_id": vehicle.get("model_id"),
                "year_from": None, "year_to": None, "price_from": None, "price_to": None}
    if vehicle.get("make_id"):
        pairs.append(("mmmv", f"{vehicle['make_id']}|{vehicle.get('model_id') or ''}||"))
    year = (vehicle.get("first_registration") or "")[:4]
    if year.isdigit():
        criteria["year_from"], criteria["year_to"] = int(year) - 2, int(year) + 2
        pairs += [("fregfrom", str(int(year) - 2)), ("fregto", str(int(year) + 2))]
    amount = (record.get("price") or {}).get("amount")
    if isinstance(amount, (int, float)) and amount > 0:
        criteria["price_from"], criteria["price_to"] = int(amount * 0.8), int(math.ceil(amount * 1.2))
        pairs += [("pricefrom", str(criteria["price_from"])), ("priceto", str(criteria["price_to"]))]
    pairs += [("sort", "standard"), ("desc", "0")]
    props = fetch.fetch_search("/lst", pairs + [("page", "1"), ("size", str(limit + 1))])
    parsed = parsers.parse_search(props)
    results = [r for r in parsed["results"] if r["id"] != record.get("id")][:limit]
    return {
        "listing": {"id": record.get("id"), "title": record.get("title"), "link": record.get("link")},
        "criteria": criteria,
        "search_link": _search_link("/lst", pairs),
        "total_count": parsed["total_count"],
        "count": len(results),
        "results": results,
    }


def listing_similar(**data):
    return cached_call("autoscout24.similar", data, _similar, ttl.SIMILAR_CACHE)


# ---- listings/count -------------------------------------------------------------------------

_COUNT_QUERY = """query Counts($locale: Locale_!, $queryString: String!, $withModels: Boolean!) {
  search {
    listingsByQueryString(locale: $locale, queryString: $queryString) { metadata { totalItems } }
    facetCounters(locale: $locale, queryString: $queryString) {
      make { id count }
      model @include(if: $withModels) { id count }
      modelGroup @include(if: $withModels) { id count }
      fuel { id count } transmission { id count } bodyType { id count } driveTrain { id count }
      usageState { id count } customerType { id count } bodyColorId { id count }
      upholsteryMaterial { id count } equipment { id count }
    }
  }
}"""


def _facet(entries, options, coded=False):
    """Counter entries -> rows with the taxonomy's labels, most frequent
    first: {"id", "name", "count"} for id-keyed options (makes, body types,
    colours, equipment), {"value", "code", "name", "count"} for coded ones
    (fuel, transmission...: `value` is the search param value)."""
    by_code = {str(o.get("code") if coded else o.get("id")): o for o in options or []}
    out = []
    for entry in entries or []:
        code = str(entry.get("id"))
        option = by_code.get(code) or {}
        if coded:
            row = {"value": option.get("value"), "code": code, "name": option.get("name")}
        else:
            row = {"id": int(code) if code.isdigit() else code, "name": option.get("name")}
        row["count"] = parsers._int(entry.get("count"))
        out.append(row)
    return sorted(out, key=lambda r: -(r["count"] or 0))


def _graphql_counts(query_string, with_models):
    data = fetch.graphql(_COUNT_QUERY, {"locale": fetch.GRAPHQL_LOCALE, "queryString": query_string,
                                        "withModels": with_models}, label="listing counts")
    search = data.get("search") or {}
    total = ((search.get("listingsByQueryString") or {}).get("metadata") or {}).get("totalItems")
    return parsers._int(total), search.get("facetCounters") or {}


def _count(**filters):
    vehicle_type = filters["vehicle_type"]
    make = resolve_make(vehicle_type, filters.get("make"))
    model = resolve_model(vehicle_type, make, filters.get("model"))
    pairs = _filter_params(filters, make, model)
    total, facets = _graphql_counts(urlencode(pairs), with_models=bool(make))
    taxonomy = _taxonomy(vehicle_type)
    options = taxonomy["filters"]
    makes = [{"id": m["id"], "name": m["name"]} for m in taxonomy["makes"]]
    out = {
        "makes": _facet(facets.get("make"), makes),
        "models": None,
        "model_groups": None,
        "fuel_types": _facet(facets.get("fuel"), options["fuel_types"], coded=True),
        "transmissions": _facet(facets.get("transmission"), options["transmissions"], coded=True),
        "drivetrains": _facet(facets.get("driveTrain"), options["drivetrains"], coded=True),
        "body_types": _facet(facets.get("bodyType"), options["body_types"]),
        "seller_types": _facet(facets.get("customerType"), options["seller_types"], coded=True),
        "usage_states": [{"value": _USAGE_STATES.get(str(e.get("id"))), "code": str(e.get("id")),
                          "count": parsers._int(e.get("count"))} for e in facets.get("usageState") or []],
        "body_colors": _facet(facets.get("bodyColorId"), options["body_colors"]),
        "upholstery": _facet(facets.get("upholsteryMaterial"), options["upholstery"], coded=True),
        "equipment": _facet(facets.get("equipment"), options["equipment"]),
    }
    if make:
        catalog = _catalog(vehicle_type, make["id"])
        out["models"] = _facet(facets.get("model"), catalog["models"])
        out["model_groups"] = _facet(facets.get("modelGroup"), catalog["model_groups"])
    return {
        "total_count": total,
        "reachable_count": _reachable(total),
        "search_link": _search_link("/lst", pairs),
        "filters": _filters_echo(filters, make, model),
        "facets": out,
    }


def listings_count(**data):
    return cached_call("autoscout24.count", data, _count, ttl.COUNT_CACHE)


# ---- dealers (one cached dealer page parse) ------------------------------------------------

def _dealer_record(dealer):
    return parsers.parse_dealer_page(fetch.fetch_dealer(dealer))


def _dealer(dealer):
    return cached_call("autoscout24.dealer", {"dealer": dealer}, _dealer_record, ttl.DEALER_CACHE)


def _dealer_identity(record):
    return {"id": record.get("id"), "slug": record.get("slug"), "name": record.get("name"),
            "link": record.get("link")}


def dealer_details(dealer):
    """The dealer profile; listings and reviews come as counts here (their
    lists are dealers/listings and dealers/reviews)."""
    record = _dealer(dealer)
    return {k: v for k, v in record.items() if k not in ("listings", "reviews")}


def _dealer_pagination(page, total, results, size):
    if not results and page > 1 and not total:
        return {"page": page, "items_per_page": size, "has_next": False, "total_pages": None, "total_count": None}
    total = total or 0
    return {"page": page, "items_per_page": size, "total_pages": math.ceil(total / size) if total else 0,
            "total_count": total}


def _dealer_listings(dealer, vehicle_type, make, model, variant, price_from, price_to, year_from, year_to,
                     mileage_from, mileage_to, sort, order, page):
    filtered = any(v is not None for v in (vehicle_type, make, model, variant, price_from, price_to, year_from,
                                           year_to, mileage_from, mileage_to))
    if not filtered and page == 1 and sort == "standard" and order == "0":
        record = _dealer(dealer)          # the home page shows exactly this page
        results, total = record["listings"], record["listings_count"]
    else:
        type_code = vehicle_type or "C"
        make_ref = resolve_make(type_code, make)
        model_ref = resolve_model(type_code, make_ref, model)
        params = []
        if vehicle_type:
            params.append(("atype", vehicle_type))
        params.append(("page", str(page)))
        if make_ref:
            model_id = model_ref["id"] if model_ref and model_ref["kind"] == "model" else ""
            params.append(("mmm", f"{make_ref['id']}|{model_id}|{(variant or '').strip()}"))
        for key, value in (("pricefrom", price_from), ("priceto", price_to), ("fregfrom", year_from),
                           ("fregto", year_to), ("kmfrom", mileage_from), ("kmto", mileage_to)):
            if value is not None:
                params.append((key, str(value)))
        if sort != "standard" or order != "0":
            params += [("sort", sort), ("desc", order)]
        parsed = parsers.parse_dealer_page(fetch.fetch_dealer(dealer, "list", params))
        record = parsed
        results, total = parsed["listings"], parsed["listings_count"]
    return {
        "dealer": _dealer_identity(record),
        "results": results,
        "pagination": _dealer_pagination(page, total, results, DEALER_PAGE_SIZE),
    }


def dealer_listings(**data):
    return cached_call("autoscout24.dealer_listings", data, _dealer_listings, ttl.DEALER_LISTINGS_CACHE)


def _review_page(customer_id, page):
    return {"reviews": parsers.parse_reviews(fetch.fetch_reviews(customer_id, (page - 1) * REVIEWS_PAGE_SIZE))}


def dealer_reviews(dealer, page):
    """Newest first, 10 per page: page 1 ships with the dealer page, later
    pages come from the page's own fetch-reviews call."""
    record = _dealer(dealer)
    rating = record.get("rating") or {}
    total = rating.get("review_count") or 0
    if page == 1:
        reviews = record["reviews"]
    elif record.get("id") is None or (page - 1) * REVIEWS_PAGE_SIZE >= total:
        reviews = []
    else:
        reviews = cached_call("autoscout24.dealer_reviews", {"customer_id": record["id"], "page": page},
                              _review_page, ttl.DEALER_REVIEWS_CACHE)["reviews"]
    return {
        "dealer": _dealer_identity(record),
        "rating": rating or None,
        "results": reviews,
        "pagination": {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                       "total_pages": math.ceil(total / REVIEWS_PAGE_SIZE) if total else 0, "total_count": total},
    }


# ---- taxonomy --------------------------------------------------------------------------------

def _makes(vehicle_type, country):
    makes = _taxonomy(vehicle_type)["makes"]
    _, facets = _graphql_counts(urlencode([("atype", vehicle_type), ("cy", country)]), with_models=False)
    counts = parsers.counts_by_id(facets.get("make"))
    rows = [{**m, "listings_count": counts.get(str(m["id"]), 0)} for m in makes]
    return {"vehicle_type": _type_name(vehicle_type), "country": _country_iso(country),
            "count": len(rows), "makes": rows}


def taxonomy_makes(**data):
    return cached_call("autoscout24.makes", data, _makes, ttl.MAKES_CACHE)


def _models(make, vehicle_type, country):
    make_ref = resolve_make(vehicle_type, make)
    catalog = _catalog(vehicle_type, make_ref["id"])
    model_counts, group_counts = {}, {}
    if catalog["models"] or catalog["model_groups"]:
        query = urlencode([("atype", vehicle_type), ("cy", country), ("mmvmk0", str(make_ref["id"]))])
        _, facets = _graphql_counts(query, with_models=True)
        model_counts = parsers.counts_by_id(facets.get("model"))
        group_counts = parsers.counts_by_id(facets.get("modelGroup"))
    return {
        "make": make_ref,
        "vehicle_type": _type_name(vehicle_type),
        "country": _country_iso(country),
        "models": [{**m, "listings_count": model_counts.get(str(m["id"]), 0)} for m in catalog["models"]],
        "model_groups": [{**g, "listings_count": group_counts.get(str(g["id"]), 0)} for g in catalog["model_groups"]],
        "model_lines": catalog["model_lines"],
    }


def taxonomy_models(**data):
    return cached_call("autoscout24.models", data, _models, ttl.MODELS_CACHE)


_FREETEXT_QUERY = """query ModelFreeTextSearchV2($searchTerm: String, $limit: Int, $vehicleTypeId: String,
  $marketplaces: String) {
  getFreeTextTaxonomyV2(searchTerm: $searchTerm, limit: $limit, vehicleTypeId: $vehicleTypeId,
    marketplaces: $marketplaces) {
    totalCount isExactMatch
    items { displayName cat title subtitle shortTitle canDrillDown listingsCount }
  }
}"""


def _taxonomy_search(query, vehicle_type, country, limit):
    data = fetch.graphql(_FREETEXT_QUERY, {"searchTerm": query, "limit": limit, "vehicleTypeId": vehicle_type,
                                           "marketplaces": refs.MARKETPLACE_OF_CODE.get(country, "DE")},
                         label="model search")
    results = parsers.parse_taxonomy_search(data)[:limit]
    for row in results:
        row["search_link"] = (_search_link("/lst", [("atype", vehicle_type), ("cy", country), ("cat", row["category"])])
                              if row["category"] else None)
    found = (data.get("getFreeTextTaxonomyV2") or {})
    return {"query": query, "vehicle_type": _type_name(vehicle_type), "country": _country_iso(country),
            "is_exact_match": bool(found.get("isExactMatch")), "count": len(results), "results": results}


def taxonomy_search(**data):
    return cached_call("autoscout24.taxonomy_search", data, _taxonomy_search, ttl.TAXONOMY_SEARCH_CACHE)


def taxonomy_filters(vehicle_type):
    return {"vehicle_type": _type_name(vehicle_type), **_taxonomy(vehicle_type)["filters"]}


# ---- locations ----------------------------------------------------------------------------------

def _locations(query, country):
    iso = refs.COUNTRY_OF_CODE[country]
    postcode = bool(re.fullmatch(r"[0-9 -]{2,}", query))
    results = parsers.parse_locations(fetch.fetch_locations(iso, query, postcode=postcode))
    return {"query": query, "country": iso, "count": len(results), "results": results}


def locations_autocomplete(**data):
    return cached_call("autoscout24.locations", data, _locations, ttl.LOCATIONS_CACHE)
