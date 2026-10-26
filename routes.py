"""The 13 AutoScout24 endpoints. Every path is served with and without the
`/autoscout24` prefix, so code generated against the hosted API on RapidAPI
(paths like /listings/details) runs unchanged against this server.

Each request is validated by the endpoint's schema (autoscout24/schemas.py:
unknown params, bad values and missing required params are a 400 naming the
field), then the endpoint function runs. Errors map to HTTP the same way the
hosted API does: bad params 400, missing listing / dealer 404, AutoScout24
blocking or failing 502, anything else 500. Paged endpoints answer with
count / per_page / current_page / total_pages / next / previous first."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from autoscout24 import api, schemas
from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

PREFIX = "/autoscout24"


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "München" would arrive as "MÃ¼nchen")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{request.path}?{urlencode(query, doseq=True)}"


def paginate(result, raw_params):
    """Lift the endpoint's `pagination` block into the flat shape, with
    next / previous links rebuilt from the caller's own params. When the
    site publishes no total, `has_next` drives the next link and the totals
    stay null."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _int(pagination.get("page")) or _int(raw_params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _int(total_pages, None)
    else:
        total_pages = max(_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(raw_params, page + 1 if has_next else None),
        "previous": _page_link(raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(schema_cls, impl, label, paginated=False):
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"autoscout24 rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"autoscout24 blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"autoscout24 {label} failed: {e}"}, 502)
    except Exception as e:
        return json_response({"error": f"autoscout24 {label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, raw)
    return json_response(result)


# path, schema, endpoint function, paged — in the order the API docs list them
ENDPOINTS = [
    ("/listings/details", schemas.ListingSchema, api.listing_details, False),
    ("/listings/search", schemas.SearchSchema, api.listings_search, True),
    ("/listings/by-link", schemas.ByLinkSchema, api.listings_by_link, True),
    ("/taxonomy/search", schemas.TaxonomySearchSchema, api.taxonomy_search, False),
    ("/locations/autocomplete", schemas.LocationsSchema, api.locations_autocomplete, False),
    ("/listings/similar", schemas.SimilarSchema, api.listing_similar, False),
    ("/listings/count", schemas.CountSchema, api.listings_count, False),
    ("/dealers/details", schemas.DealerSchema, api.dealer_details, False),
    ("/dealers/listings", schemas.DealerListingsSchema, api.dealer_listings, True),
    ("/dealers/reviews", schemas.DealerReviewsSchema, api.dealer_reviews, True),
    ("/taxonomy/makes", schemas.MakesSchema, api.taxonomy_makes, False),
    ("/taxonomy/models", schemas.ModelsSchema, api.taxonomy_models, False),
    ("/taxonomy/filters", schemas.FiltersSchema, api.taxonomy_filters, False),
]


def mount(path, schema_cls, impl, paginated):
    """Serve one endpoint at /path and /autoscout24/path."""
    label = path.strip("/")

    def handler():
        return call(schema_cls, impl, label, paginated)
    handler.__name__ = "autoscout24_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
