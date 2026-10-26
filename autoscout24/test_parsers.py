"""Offline tests for the AutoScout24 parsers, reference resolvers, value
helpers, the endpoint functions (fetch stubbed with fixtures) and the
transport's error mapping (a fake session).

    python -m pytest autoscout24/test_parsers.py -q

Fixtures are real www.autoscout24.com payloads captured 2026-10-24
(autoscout24/fixtures/, listed in parsers.py's docstring). No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoscout24 import api, fetch, refs  # noqa: E402
from autoscout24 import parsers as P  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
GUID = "a3c3a1a1-c798-41eb-b399-02659e4fd9f5"


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def props(name):
    """pageProps of a data-route JSON or a rendered page fixture."""
    if name.endswith(".json"):
        return fixture(name)["pageProps"]
    return P.next_data(fixture(name))["props"]["pageProps"]


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    GUID, GUID.upper(),
    f"https://www.autoscout24.com/offers/renault-zoe-intens-electric-white-cat_ma60mo20228-{GUID}",
    f"https://www.autoscout24.de/angebote/renault-zoe-{GUID}?source=list",
    f"https://www.autoscout24.it/annunci/x-{GUID}/",
    f"www.autoscout24.com/offers/{GUID}",
])
def test_resolve_listing(value):
    assert refs.resolve_listing(value) == GUID


@pytest.mark.parametrize("value,message", [
    ("not-a-listing", "listing id"),
    ("https://www.example.com/offers/" + GUID, "AutoScout24 link"),
    ("https://www.autoscout24.ch/de/d/" + GUID, "different platform"),
    ("https://www.autoscout24.com/lst?atype=C", "offer link"),
])
def test_resolve_listing_rejects(value, message):
    with pytest.raises(ValueError, match=message):
        refs.resolve_listing(value)


@pytest.mark.parametrize("value,expected", [
    ("autohaus-heinrich-gmbh", "autohaus-heinrich-gmbh"),
    ("5623", "5623"),
    ("https://www.autoscout24.com/dealerinfo/autohaus-heinrich-gmbh?atype=C", "autohaus-heinrich-gmbh"),
    ("https://www.autoscout24.de/haendler/h-und-m-automobile-gmbh/bewertungen", "h-und-m-automobile-gmbh"),
    ("https://www.autoscout24.it/concessionari/cars-21-srls?atype=C", "cars-21-srls"),
    ("https://www.autoscout24.fr/garages/emporio-automobile", "emporio-automobile"),
    ("https://www.autoscout24.nl/autobedrijven/hermans-collectables", "hermans-collectables"),
    ("https://www.autoscout24.es/profesionales/dma-automocion-luxury", "dma-automocion-luxury"),
    ("https://www.autoscout24.lu/professional/eurocar-diffusion-foetz-3895-1", "eurocar-diffusion-foetz-3895-1"),
    ("https://www.autoscout24.com/dealerinfo/5623/list", "5623"),
])
def test_resolve_dealer(value, expected):
    assert refs.resolve_dealer(value) == expected


@pytest.mark.parametrize("value", ["", "Autohaus Heinrich GmbH", "https://www.autoscout24.com/lst?atype=C",
                                   "https://www.example.com/dealerinfo/x"])
def test_resolve_dealer_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_dealer(value)


def test_resolve_search_link():
    link = refs.resolve_search_link("https://www.autoscout24.de/lst/bmw/3er-(alle)?atype=C&fregfrom=2020")
    assert link == {"tld": "de", "path": "/lst/bmw/3er-(alle)", "params": [("atype", "C"), ("fregfrom", "2020")]}
    assert refs.resolve_search_link("https://www.autoscout24.be/nl/lst?atype=C")["path"] == "/nl/lst"
    assert refs.resolve_search_link("https://www.autoscout24.com/lst-moto")["path"] == "/lst-moto"
    with pytest.raises(ValueError, match="/lst"):
        refs.resolve_search_link(f"https://www.autoscout24.com/offers/{GUID}")
    with pytest.raises(ValueError):
        refs.resolve_search_link("audi a4")


def test_dealer_token_of():
    assert refs.dealer_token_of("https://www.autoscout24.com/dealerinfo/autohaus-x/about-us") == "autohaus-x"
    assert refs.dealer_token_of("/lst?atype=C&cid=64579553") is None
    assert refs.dealer_token_of(None) is None


# ---- value helpers ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("1,968 cc", 1968), ("211,000 km", 211000), ("7.60 l/100 km", 7.6), ("4,8", 4.8), ("6 kW", 6),
    (13990, 13990), (None, None), ("- (g/km)", None), (True, None),
])
def test_number(value, expected):
    assert P._number(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("€ 12,990,-", 12990), ("€ 1.890,-", 1890), ("€ 2.375,83", 2375.83), ("€ 64,900", 64900), ("", None),
])
def test_amount(value, expected):
    assert P._amount(value) == expected


def test_dates():
    assert P._month("2021-08-01") == "2021-08"
    assert P._month("08/2021") == "2021-08"
    assert P._month("10-2007") == "2007-10"
    assert P._month("junk") is None
    assert P._date("14/01/2027") == "2027-01-14"
    assert P._date("09.10.2026") == "2026-10-09"
    assert P._date(None) is None
    assert P._timestamp("2026-10-23T09:47:09.116Z") == "2026-10-23T09:47:09Z"
    assert P._timestamp("2026-10-23T11:47:09+02:00") == "2026-10-23T09:47:09Z"


def test_image_upscale_and_price_rating():
    thumb = f"https://prod.pictures.autoscout24.net/listing-images/{GUID}_abc.jpg/250x188.webp"
    assert P._image(thumb).endswith("_abc.jpg/1280x960.webp")
    assert P.price_rating("toolow-price ") == "too_low_price"
    assert P.price_rating("somewhat-expensive") == "somewhat_expensive"
    assert P.price_rating("unknown") is None


def test_html_to_text():
    text = P.html_to_text("<strong>Extras</strong><br /> <br /><ul><li>Navi </li><li>AHK</li></ul>Ende &amp; aus")
    assert text == "Extras\n\n- Navi\n- AHK\nEnde & aus"
    assert P.html_to_text("") is None


def test_parse_category():
    assert P.parse_category("ma74mo2084_gti") == {"make_id": 74, "model_id": 2084, "model_group_id": None,
                                                 "model_line_id": None, "variant_id": None, "version": "gti"}
    assert P.parse_category("ma74gr100101va179")["variant_id"] == 179
    assert P.parse_category("ma13ml38")["model_line_id"] == 38
    assert P.parse_category("bogus")["make_id"] is None


# ---- search ------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cars():
    return P.parse_search(props("search_cars_de_p1.json"))


def test_search_page(cars):
    assert cars["total_count"] == 839717
    assert cars["total_pages"] == 200          # the site's 4,000-result cap at 20 per page
    assert len(cars["results"]) == 20
    assert cars["query"]["atype"] == "C" and cars["query"]["cy"] == "D"


def test_search_listing_shape(cars):
    zoe = cars["results"][0]
    assert list(zoe)[:5] == ["id", "title", "link", "price", "vehicle"]
    assert zoe["id"] == GUID and zoe["title"] == "Renault ZOE"
    assert zoe["link"].startswith("https://www.autoscout24.com/offers/") and zoe["link"].endswith(GUID)
    assert zoe["price"] == {"amount": 13990, "currency": "EUR", "is_vat_deductible": True, "is_conditional": False,
                            "previous_amount": None, "suggested_retail_price": None, "rating": "top_price"}
    v = zoe["vehicle"]
    assert (v["type"], v["make"], v["model"], v["condition"]) == ("car", "Renault", "ZOE", "used")
    assert (v["mileage_km"], v["first_registration"], v["power_kw"], v["power_hp"]) == (17188, "2021-08", 99, 135)
    assert (v["make_id"], v["model_id"], v["model_group_id"], v["trim_id"]) == (60, 20228, 201273, 4628)
    assert v["electrification"] == "electric"
    assert zoe["images"][0].endswith("/1280x960.webp") and zoe["image_count"] == len(zoe["images"])
    s = zoe["seller"]
    assert (s["type"], s["slug"]) == ("dealer", "autohaus-heinrich-gmbh")
    assert s["link"] == "https://www.autoscout24.com/dealerinfo/autohaus-heinrich-gmbh"
    assert s["phones"][0]["e164"].startswith("+49")
    assert zoe["location"]["country_code"] == "DE"
    assert {r["price"]["currency"] for r in cars["results"]} == {"EUR"}


def test_search_values_are_never_empty_strings(cars):
    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        else:
            assert value != "" and value != "N/A"
    walk(cars["results"])


def test_search_private_sellers():
    results = P.parse_search(props("search_private_de.json"))["results"]
    seller = results[0]["seller"]
    assert seller["type"] == "private" and seller["name"] is None and seller["link"] is None
    assert seller["listings_link"] == "https://www.autoscout24.com/lst?atype=C&cid=64579553"
    assert seller["phones"][0]["type"] == "private"


def test_search_ev_consumption_and_motorbikes_and_transporters():
    ev = P.parse_search(props("search_electric_de.json"))["results"][0]["vehicle"]
    assert (ev["fuel_consumption"], ev["fuel_consumption_unit"], ev["co2_emissions_g_per_km"]) == (14.9, "kWh/100 km", 0)
    bikes = P.parse_search(props("search_motorbikes_de.json"))["results"]
    assert {r["vehicle"]["type"] for r in bikes} == {"motorbike"}
    vans = P.parse_search(props("search_transporters_de.json"))["results"]
    no_model = [r for r in vans if r["vehicle"]["model"] is None]
    assert no_model and no_model[0]["vehicle"]["version"] and no_model[0]["vehicle"]["type"] == "transporter"


def test_search_empty_pages():
    assert P.parse_search(props("search_no_results.json"))["results"] == []
    past = P.parse_search(props("search_past_end.json"))
    assert (past["results"], past["total_count"], past["total_pages"]) == ([], 0, 0)
    assert P.parse_search({}) == {"results": [], "total_count": None, "total_pages": None, "query": {}}
    assert P.parse_search_listing({"id": "x"})["vehicle"]["make"] is None


# ---- listing details ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def zoe():
    return P.parse_listing(props("details_dealer_ev.json"))


def test_listing_identity_and_price(zoe):
    assert list(zoe)[:6] == ["id", "title", "link", "status", "price", "vehicle"]
    assert (zoe["id"], zoe["status"], zoe["created_at"]) == (GUID, "active", "2026-10-23T09:47:09Z")
    price = zoe["price"]
    assert (price["amount"], price["currency"], price["vat_rate"], price["is_vat_deductible"]) == (13990, "EUR", 19, True)
    assert price["dealer_amount"] is None     # same as the public price


def test_listing_vehicle(zoe):
    v = zoe["vehicle"]
    assert (v["make"], v["model"], v["generation"], v["version"]) == (
        "Renault", "ZOE", "1. Generation", "Intens R135 ZE 50 Kaufbatterie CCS Klima")
    assert (v["mileage_km"], v["first_registration"], v["previous_owners"]) == (17188, "2021-08", 1)
    assert v["history"]["next_inspection"] == "2026-08" and v["history"]["is_accident_free"] is True
    assert (v["engine"]["power_kw"], v["engine"]["empty_weight_kg"]) == (99, 1577)
    assert (v["fuel"]["category"], v["fuel"]["electric_range_km"], v["fuel"]["powertrain"]) == ("Electric", 200, "ev")
    assert v["environment"]["emission_sticker"] == "4 (Green)"
    assert set(v["equipment"]) == {"comfort_and_convenience", "entertainment_and_media", "extras", "safety_and_security"}
    assert 30 in v["equipment_ids"]
    assert v["hsn_tsn"] == "3333/BMT"


def test_listing_seller_and_partners(zoe):
    s = zoe["seller"]
    assert (s["id"], s["slug"], s["customer_since"], s["language"]) == ("20123", "autohaus-heinrich-gmbh", 2006, "de-DE")
    assert s["opening_hours"][0]["days"][0] == {"day": "monday", "is_closed": False,
                                                "hours": [{"opens": "08:00", "closes": "18:00"}]}
    assert s["opening_hours"][0]["days"][6]["is_closed"] is True
    assert [c["category"] for c in s["rating"]["categories"]][0] == "overall_impression"
    assert s["rating"]["average"] == 4.8
    assert zoe["financing"][0]["provider"] == "Procheck24" and zoe["financing"][0]["monthly_rate"] == 199.46
    assert zoe["insurance"][0]["liability_monthly"] == 13.66
    assert zoe["history_report"]["provider"] == "Carfax" and zoe["history_report"]["is_free"] is True
    assert zoe["location"]["latitude"] == 50.78259
    assert zoe["identifiers"]["offer_reference"] == "847507"
    assert zoe["description"].startswith("Sonderausstattung\n\n- ")


def test_listing_html_page_matches_data_route(zoe):
    assert P.parse_listing(props("offer_page.html")) == zoe


def test_listing_private_motorbike_caravan():
    private = P.parse_listing(props("details_private_car.json"))
    assert private["seller"]["type"] == "private" and private["seller"]["listings_link"].endswith("cid=64579553")
    assert private["seller"]["rating"] is None and private["financing"] is not None
    bike = P.parse_listing(props("details_motorbike.json"))
    assert bike["vehicle"]["type"] == "motorbike" and bike["vehicle"]["engine"]["displacement_cc"] == 107
    # five labelled categories: German labels name them
    assert [c["category"] for c in bike["seller"]["rating"]["categories"]][-1] == "purchase_process"
    caravan = P.parse_listing(props("details_caravan.json"))
    assert caravan["vehicle"]["type"] == "caravan"
    assert caravan["vehicle"]["dimensions"]["length_mm"] == 5860


def test_listing_sparse_payload():
    record = P.parse_listing({"listingDetails": {"id": GUID.upper()}})
    assert record["id"] == GUID and record["price"]["amount"] is None
    assert record["vehicle"]["make"] is None and record["images"] == [] and record["financing"] == []
    assert P.parse_listing({})["id"] is None


# ---- dealers ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def autoexpo():
    return P.parse_dealer_page(props("dealer_home.html"))


def test_dealer_page(autoexpo):
    assert list(autoexpo)[:4] == ["id", "slug", "name", "link"]
    assert (autoexpo["id"], autoexpo["slug"], autoexpo["listings_count"]) == (5623, "autoexpo-deutsche-automarkt-gmbh", 1229)
    assert autoexpo["address"] == {"street": "Rudolf-Diesel-Straße 7", "zip": "35463", "city": "Fernwald-Steinbach",
                                   "country_code": "DE"}
    assert autoexpo["phones"] == [{"number": "+49 (0)6404 - 50639992", "e164": "+49640450639992"}]
    assert autoexpo["rating"]["review_count"] == 741 and autoexpo["reviews_count"] == 741
    assert [c["category"] for c in autoexpo["rating"]["categories"]][-1] == "consultancy"
    assert autoexpo["services"] == ["Financial services", "Insurance"]
    assert len(autoexpo["listings"]) == 20 and len(autoexpo["reviews"]) == 10
    assert autoexpo["opening_hours"][0]["days"][5]["is_closed"] is True


def test_dealer_listing_and_review_shapes(autoexpo):
    listing = autoexpo["listings"][0]
    assert listing["title"] == "Mercedes-Benz CLA 250" and listing["vehicle"]["condition"] == "used"
    assert listing["vehicle"]["additional_fuels"] == ["Electricity"]
    assert listing["price"]["amount"] == 23690 and listing["images"][0].endswith("/1280x960.webp")
    review = autoexpo["reviews"][0]
    assert (review["date"], review["author"], review["rating"]) == ("2026-10-09", "WOLF", 3)
    assert len(review["grades"]) == 6 and review["grades"][0]["category"] == "overall_impression"


def test_dealer_small_and_past_end_pages():
    small = P.parse_dealer_page(props("dealer_small_home.html"))
    assert small["contact_persons"][0] == {"name": "Darius Schmidt", "position": "Gebrauchtwagen"}
    past = P.parse_dealer_page(props("dealer_list_past_end.html"))
    assert (past["listings"], past["listings_count"], past["id"]) == ([], 0, 5623)
    assert P.parse_dealer_page({})["listings"] == []


def test_reviews_api_payloads():
    reviews = P.parse_reviews(fixture("dealer_reviews_skip20.json"))
    assert len(reviews) == 10 and reviews[0]["date"] == "2026-02-28"
    # five unlabelled grades plus a labelled one: only the label names a category
    assert [g["category"] for g in reviews[0]["grades"]] == [None, None, None, None, "consultancy"]
    assert P.parse_reviews(fixture("dealer_reviews_past_end.json")) == []
    assert P.parse_reviews(None) == []


# ---- taxonomy / counts / places ---------------------------------------------------------------------

def test_filters_and_makes():
    taxonomy = props("filters_cars.html")["taxonomy"]
    makes = P.parse_makes(taxonomy)
    assert len(makes) == 301 and {"id": 9, "name": "Audi", "is_top_make": True} in makes
    filters = P.parse_filters(taxonomy)
    assert {"value": "gasoline", "code": "B", "name": "Gasoline"} in filters["fuel_types"]
    assert {"id": 4, "name": "SUV/Off-Road/Pick-Up"} in filters["body_types"]
    assert filters["countries"][0] == {"value": "EU", "code": "A,B,D,E,F,I,L,NL", "name": "Europe"}
    assert {"value": "newest", "code": "age", "name": "Latest offers first"} in filters["sort_options"]
    assert filters["first_registration_years"]["to"] >= 2026
    trailers = P.parse_filters(props("filters_trailers.html")["taxonomy"])
    assert trailers["fuel_types"] == [] and trailers["axles"] == [1, 2, 3, 4]
    assert P.parse_filters({})["body_types"] == [] and P.parse_makes(None) == []


def test_models_with_counts():
    facets = fixture("graphql_count_audi.json")["data"]["search"]["facetCounters"]
    models = P.parse_models(fixture("models_audi.json"), P.counts_by_id(facets["model"]),
                            P.counts_by_id(facets["modelGroup"]))
    a4 = next(m for m in models["models"] if m["name"] == "A4")
    assert a4["id"] == 1626 and a4["listings_count"] == 7481
    assert models["model_lines"] == []
    assert P.parse_models(None) == {"models": [], "model_groups": [], "model_lines": []}
    empty = fixture("graphql_count_empty.json")["data"]["search"]
    assert empty["listingsByQueryString"]["metadata"]["totalItems"] == 0 and P.counts_by_id(empty["facetCounters"]["make"]) == {}


def test_taxonomy_search_and_locations():
    results = P.parse_taxonomy_search(fixture("graphql_freetext_golf.json")["data"])
    assert results[0]["name"] == "Volkswagen Golf" and results[0]["make_id"] == 74
    assert results[0]["model_group_id"] == 100101 and results[0]["has_children"] is True
    assert P.parse_taxonomy_search({}) == []
    places = P.parse_locations(fixture("locations_berlin.json"))
    assert places[0]["label"] == "Berlin" and places[0]["latitude"] == 52.52343
    assert P.parse_locations(fixture("locations_empty.json")) == []


def test_not_found_page():
    html = fixture("not_found.html")
    assert P.next_data(html) is None and P.page_title(html) == "Error Pages"


# ---- endpoint functions (fetch stubbed with the fixtures) --------------------------------------

@pytest.fixture
def stub(monkeypatch):
    calls = []

    def search(path="/lst", params=()):
        calls.append(("search", path, list(params)))
        page = dict(params).get("page")
        return props("search_past_end.json" if page == "200" else "search_cars_de_p1.json")

    monkeypatch.setattr(fetch, "fetch_search", search)
    monkeypatch.setattr(fetch, "fetch_search_page", lambda vt: props("filters_cars.html"))
    monkeypatch.setattr(fetch, "fetch_models", lambda catalog, make_id: fixture("models_audi.json"))
    monkeypatch.setattr(fetch, "fetch_listing", lambda guid: fixture("details_dealer_ev.json")["pageProps"])
    monkeypatch.setattr(fetch, "graphql", lambda q, v, label="": fixture("graphql_count_audi.json")["data"])

    def dealer(token, sub="", params=()):
        calls.append(("dealer", token, sub, list(params)))
        return props("dealer_list_past_end.html" if dict(params).get("page") == "999" else "dealer_home.html")

    monkeypatch.setattr(fetch, "fetch_dealer", dealer)
    monkeypatch.setattr(fetch, "fetch_reviews", lambda cid, skip: calls.append(("reviews", cid, skip)) or
                        fixture("dealer_reviews_skip20.json"))
    monkeypatch.setattr(api, "cached_call", lambda ns, data, fn, ttl, **kw: fn(**data))
    return calls


def _search_args(**overrides):
    from autoscout24.schemas import SearchSchema
    return {**SearchSchema().load({}), **overrides}


def test_search_builds_site_query(stub):
    out = api.listings_search(**_search_args(make="audi", model="A4", fuel=["D"], price_to=30000, page_size=5))
    _, path, params = stub[0]
    assert path == "/lst"
    assert ("mmmv", "9|1626||") in params and ("fuel", "D") in params and ("size", "5") in params
    assert out["filters"]["make"] == {"id": 9, "name": "Audi"}
    assert out["filters"]["model"] == {"kind": "model", "id": 1626, "name": "A4"}
    assert out["pagination"] == {"page": 1, "items_per_page": 5, "total_pages": 200, "total_count": 839717}
    assert out["reachable_count"] == 4000 and out["search_link"].startswith("https://www.autoscout24.com/lst?")


def test_numeric_model_names_and_ids(stub, monkeypatch):
    catalog = {"models": [{"id": 1950, "name": "911", "model_line_id": None}, {"id": 1626, "name": "A4"}],
               "model_groups": [], "model_lines": []}
    monkeypatch.setattr(api, "_catalog", lambda vt, make_id: catalog)
    make = {"id": 57, "name": "Porsche"}
    assert api.resolve_model("C", make, "911") == {"kind": "model", "id": 1950, "name": "911"}
    assert api.resolve_model("C", make, "1626") == {"kind": "model", "id": 1626, "name": "A4"}
    with pytest.raises(ValueError, match="unknown model"):
        api.resolve_model("C", make, "4242")
    monkeypatch.setattr(api, "_catalog", lambda vt, make_id: {"models": [], "model_groups": [], "model_lines": []})
    assert api.resolve_model("N", make, "4242")["id"] == 4242


def test_search_unknown_make_is_a_400(stub):
    with pytest.raises(ValueError, match="unknown make"):
        api.listings_search(**_search_args(make="notamake"))


def test_search_damaged_filter_uses_ustate(stub):
    api.listings_search(**_search_args(damaged="include"))
    assert ("ustate", "A,N,U") in stub[-1][2]
    api.listings_search(**_search_args(damaged="damaged-only"))
    assert ("ustate", "A") in stub[-1][2]


def test_search_past_the_end_is_an_empty_page(stub):
    out = api.listings_search(**_search_args(page=200))
    assert out["results"] == [] and out["pagination"] == {"page": 200, "items_per_page": 20, "has_next": False,
                                                          "total_pages": None, "total_count": None}


def test_similar_slices_the_listing(stub):
    out = api.listing_similar(listing=GUID, limit=5)
    _, _, params = stub[0]
    assert ("mmmv", "60|20228||") in params and ("fregfrom", "2019") in params and ("pricefrom", "11192") in params
    assert all(r["id"] != GUID for r in out["results"]) and len(out["results"]) <= 5
    assert out["criteria"]["price_to"] == 16788


def test_count_labels_facets(stub):
    from autoscout24.schemas import CountSchema
    out = api.listings_count(**CountSchema().load({"make": "9"}))
    assert out["total_count"] == 70473 and out["filters"]["make"]["name"] == "Audi"
    assert out["facets"]["fuel_types"][0] == {"value": "gasoline", "code": "B", "name": "Gasoline", "count": 30677}
    assert out["facets"]["models"][0]["name"] == "A3"
    assert {"value": "damaged", "code": "A", "count": 2310} in out["facets"]["usage_states"]


def test_dealer_endpoints_share_the_page(stub):
    details = api.dealer_details(dealer="5623")
    assert "listings" not in details and details["reviews_count"] == 741
    first = api.dealer_listings(dealer="5623", vehicle_type=None, make=None, model=None, variant=None,
                                price_from=None, price_to=None, year_from=None, year_to=None, mileage_from=None,
                                mileage_to=None, sort="standard", order="0", page=1)
    assert first["pagination"] == {"page": 1, "items_per_page": 20, "total_pages": 62, "total_count": 1229}
    assert [c[2] for c in stub if c[0] == "dealer"] == ["", ""]     # home page only
    past = api.dealer_listings(dealer="5623", vehicle_type="C", make="audi", model=None, variant=None,
                               price_from=None, price_to=None, year_from=None, year_to=None, mileage_from=None,
                               mileage_to=None, sort="price", order="1", page=999)
    _, _, sub, params = stub[-1]
    assert sub == "list" and ("mmm", "9||") in params and ("sort", "price") in params
    assert past["results"] == [] and past["pagination"]["has_next"] is False


def test_dealer_reviews_pages(stub):
    first = api.dealer_reviews(dealer="5623", page=1)
    assert len(first["results"]) == 10 and first["pagination"]["total_pages"] == 75
    third = api.dealer_reviews(dealer="5623", page=3)
    assert ("reviews", 5623, 20) in stub and third["results"][0]["date"] == "2026-02-28"
    beyond = api.dealer_reviews(dealer="5623", page=200)
    assert beyond["results"] == [] and ("reviews", 5623, 1990) not in stub


def test_by_link_localized_slug(stub, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_localized_search",
                        lambda tld, path, params: {"pageQuery": {"cat": "ma13ml38", "mmmv": "13||38|", "atype": "C",
                                                                 "query_id": "x", "cy": "D"}})
    link = refs.resolve_search_link("https://www.autoscout24.de/lst/bmw/3er-(alle)?atype=C&page=4")
    api.listings_by_link(link=link, page=None, page_size=None)
    _, path, params = stub[-1]
    assert path == "/lst" and ("mmmv", "13||38|") in params and ("page", "4") in params
    assert not any(k == "query_id" for k, _ in params)
    link = refs.resolve_search_link("https://www.autoscout24.it/lst?atype=B")
    api.listings_by_link(link=link, page=2, page_size=50)
    _, path, params = stub[-1]
    assert path == "/lst" and ("cy", "I") in params and ("size", "50") in params


# ---- transport error mapping (fake session) -------------------------------------------------

class _Resp:
    def __init__(self, status, text="", payload=None):
        self.status_code, self.text = status, text
        self.content = (text or (json.dumps(payload) if payload is not None else "")).encode()
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses, self.urls = list(responses), []

    def request(self, method, url, **kw):
        self.urls.append(url)
        return self.responses.pop(0)

    def close(self):
        pass


@pytest.fixture
def session(monkeypatch):
    holder = {}

    def install(*responses):
        holder["s"] = _Session(responses)
        monkeypatch.setattr(fetch, "_session", lambda: holder["s"])
        monkeypatch.setattr(fetch.config, "RETRY_BACKOFF", 0)
        return holder["s"]
    return install


def test_listing_404_on_both_routes_is_not_found(session):
    s = session(_Resp(404, fixture("not_found.html")), _Resp(404, fixture("not_found.html")))
    with pytest.raises(fetch.AutoScout24NotFound, match="not found"):
        fetch.fetch_listing(GUID)
    assert s.urls[1].endswith(f"/offers/{GUID}")


def test_listing_falls_back_to_the_page(session):
    session(_Resp(404, "x"), _Resp(200, fixture("offer_page.html")))
    assert fetch.fetch_listing(GUID)["listingDetails"]["id"] == GUID


def test_refusal_is_blocked_and_retried(session):
    s = session(*[_Resp(403, fixture("not_found.html")) for _ in range(3)])
    with pytest.raises(fetch.AutoScout24Blocked):
        fetch.fetch_dealer("5623")
    assert len(s.urls) == 3


def test_search_data_route_404_reads_the_page(session):
    session(_Resp(404, "x"), _Resp(200, fixture("filters_cars.html")))
    assert "listings" in fetch.fetch_search("/lst-moto", [("cy", "D")])


def test_non_json_on_a_json_route_is_blocked(session):
    session(*[_Resp(200, "<html>challenge</html>") for _ in range(3)])
    with pytest.raises(fetch.AutoScout24Blocked):
        fetch.fetch_search("/lst", [("atype", "C")])


def test_reviews_unknown_dealer_is_empty(session):
    session(_Resp(200, ""))
    assert fetch.fetch_reviews(999999999, 10) == []


def test_graphql_errors_are_upstream(session):
    session(*[_Resp(200, payload={"errors": [{"message": "Cannot query field"}]}) for _ in range(3)])
    with pytest.raises(fetch.AutoScout24UpstreamError, match="Cannot query field"):
        fetch.graphql("{x}", {})
