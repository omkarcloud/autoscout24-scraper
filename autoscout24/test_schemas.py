"""Offline tests for the /autoscout24/* request schemas: accepted forms,
rejected forms and the error message a caller sees.

    python -m pytest autoscout24/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoscout24 import schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

GUID = "a3c3a1a1-c798-41eb-b399-02659e4fd9f5"


def errors(schema, query):
    data, body = load_query(schema, query)
    assert data is None, f"expected a 400 for {query}"
    return body["errors"]


# ---- listing -----------------------------------------------------------------------------

@pytest.mark.parametrize("value", [GUID, f"https://www.autoscout24.com/offers/renault-zoe-{GUID}",
                                   f"https://www.autoscout24.de/angebote/x-{GUID}?source=homepage"])
def test_listing_accepts_id_and_links(value):
    assert schemas.ListingSchema().load({"listing": value}) == {"listing": GUID}


@pytest.mark.parametrize("value,message", [
    ("", "Must not be empty"),
    ("12345", "listing id"),
    (f"https://www.example.com/offers/{GUID}", "AutoScout24 link"),
])
def test_listing_rejects(value, message):
    err = errors(schemas.ListingSchema, {"listing": value})
    assert message in err["listing"][0]


def test_listing_rejects_sibling_params():
    err = errors(schemas.ListingSchema, {"listing": GUID, "url": f"https://www.autoscout24.com/offers/{GUID}"})
    assert err["url"] == ["Unknown field."]
    assert "listing" in errors(schemas.ListingSchema, {})


def test_similar_limit():
    assert schemas.SimilarSchema().load({"listing": GUID}) == {"listing": GUID, "limit": 10}
    assert "limit" in errors(schemas.SimilarSchema, {"listing": GUID, "limit": "51"})


# ---- dealer ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("autohaus-heinrich-gmbh", "autohaus-heinrich-gmbh"),
    ("5623", "5623"),
    ("https://www.autoscout24.de/haendler/h-und-m-automobile-gmbh?atype=C", "h-und-m-automobile-gmbh"),
])
def test_dealer_accepts_slug_id_and_link(value, expected):
    assert schemas.DealerSchema().load({"dealer": value}) == {"dealer": expected}


def test_dealer_rejects():
    assert "dealer slug" in errors(schemas.DealerSchema, {"dealer": "Autohaus Heinrich"})["dealer"][0]
    assert "dealer page link" in errors(schemas.DealerSchema, {
        "dealer": f"https://www.autoscout24.com/offers/{GUID}"})["dealer"][0]


def test_dealer_listings_schema():
    loaded = schemas.DealerListingsSchema().load({"dealer": "5623"})
    assert loaded["vehicle_type"] is None and loaded["sort"] == "standard" and loaded["order"] == "0"
    loaded = schemas.DealerListingsSchema().load({"dealer": "5623", "vehicle_type": "motorbike", "sort": "newest",
                                                  "order": "desc", "page": "3"})
    assert (loaded["vehicle_type"], loaded["sort"], loaded["order"], loaded["page"]) == ("B", "age", "1", 3)
    assert "model" in errors(schemas.DealerListingsSchema, {"dealer": "5623", "model": "x5"})
    assert "sort" in errors(schemas.DealerListingsSchema, {"dealer": "5623", "sort": "distance"})
    assert "price_from" in errors(schemas.DealerListingsSchema, {"dealer": "5623", "price_from": "9",
                                                                "price_to": "1"})


def test_dealer_reviews_page_bounds():
    assert schemas.DealerReviewsSchema().load({"dealer": "x-y"})["page"] == 1
    assert "page" in errors(schemas.DealerReviewsSchema, {"dealer": "x-y", "page": "0"})


# ---- search -----------------------------------------------------------------------------------

def test_search_defaults():
    loaded = schemas.SearchSchema().load({})
    assert (loaded["vehicle_type"], loaded["country"], loaded["sort"], loaded["order"]) == ("C", "D", "standard", "0")
    assert (loaded["page"], loaded["page_size"], loaded["power_unit"]) == (1, 20, "kw")


def test_search_maps_readable_values_to_site_codes():
    loaded = schemas.SearchSchema().load({
        "vehicle_type": "Transporter", "country": "eu", "fuel": "diesel, electric-gasoline",
        "transmission": "automatic", "drivetrain": "4x4", "condition": "used,demonstration",
        "seller_type": "private", "upholstery": "full-leather", "body_type": "4,6,4", "equipment": "187",
        "sort": "newest", "order": "desc", "damaged": "only", "is_vat_deductible": "true", "page_size": "200",
    })
    assert loaded["vehicle_type"] == "X" and loaded["country"] == "A,B,D,E,F,I,L,NL"
    assert loaded["fuel"] == ["D", "2"] and loaded["transmission"] == ["A"] and loaded["drivetrain"] == ["4"]
    assert loaded["condition"] == ["U", "D"] and loaded["seller_type"] == "P" and loaded["upholstery"] == ["FL"]
    assert loaded["body_type"] == [4, 6] and loaded["equipment"] == [187]
    assert (loaded["sort"], loaded["order"], loaded["damaged"]) == ("age", "1", "damaged-only")
    assert loaded["is_vat_deductible"] is True and loaded["page_size"] == 200


@pytest.mark.parametrize("query,field,message", [
    ({"fuel": "coal"}, "fuel", "'coal' is not one of"),
    ({"vehicle_type": "boat"}, "vehicle_type", "Must be one of: car, motorbike"),
    ({"country": "US"}, "country", "Must be one of"),
    ({"model": "a4"}, "model", "model needs a make."),
    ({"radius": "50"}, "radius", "radius needs a location."),
    ({"sort": "distance"}, "sort", "sort=distance needs a location."),
    ({"year_from": "2022", "year_to": "2010"}, "year_from", "must not be greater than year_to"),
    ({"body_type": "suv"}, "body_type", "not a numeric id"),
    ({"page": "201"}, "page", "less than or equal to 200"),
    ({"page_size": "500"}, "page_size", "less than or equal to 200"),
    ({"price_to": "-5"}, "price_to", "greater than or equal to 1"),
    ({"is_super_deal": "maybe"}, "is_super_deal", "Must be true or false."),
    ({"colour": "1"}, "colour", "Unknown field."),
])
def test_search_rejects(query, field, message):
    err = errors(schemas.SearchSchema, query)
    assert message in " ".join(err[field])


def test_count_schema_has_no_paging():
    assert "page" in errors(schemas.CountSchema, {"page": "2"})
    assert schemas.CountSchema().load({"make": "Audi"})["make"] == "Audi"


# ---- by-link ----------------------------------------------------------------------------------

def test_by_link():
    loaded = schemas.ByLinkSchema().load({"link": "https://www.autoscout24.com/lst/audi/a4?atype=C&cy=D"})
    assert loaded["link"] == {"tld": "com", "path": "/lst/audi/a4", "params": [("atype", "C"), ("cy", "D")]}
    assert loaded["page"] is None and loaded["page_size"] is None
    assert "/lst" in errors(schemas.ByLinkSchema, {"link": f"https://www.autoscout24.com/offers/{GUID}"})["link"][0]
    assert "different platform" in errors(schemas.ByLinkSchema, {"link": "https://www.autoscout24.ch/de/s"})["link"][0]
    assert "link" in errors(schemas.ByLinkSchema, {})


# ---- taxonomy / locations ----------------------------------------------------------------------

def test_taxonomy_schemas():
    assert schemas.MakesSchema().load({}) == {"vehicle_type": "C", "country": "D"}
    assert schemas.ModelsSchema().load({"make": "Audi", "vehicle_type": "motorbike"})["vehicle_type"] == "B"
    assert "make" in errors(schemas.ModelsSchema, {})
    assert schemas.TaxonomySearchSchema().load({"query": "golf gti"})["limit"] == 10
    assert "country" in errors(schemas.TaxonomySearchSchema, {"query": "golf", "country": "EU"})
    assert schemas.FiltersSchema().load({"vehicle_type": "trailer"}) == {"vehicle_type": "L"}


def test_locations_schema():
    assert schemas.LocationsSchema().load({"query": "Berlin"}) == {"query": "Berlin", "country": "D"}
    assert schemas.LocationsSchema().load({"query": "75009", "country": "fr"})["country"] == "F"
    assert "query" in errors(schemas.LocationsSchema, {})
    assert "country" in errors(schemas.LocationsSchema, {"query": "x", "country": "CH"})


def test_every_field_has_a_description():
    for name in dir(schemas):
        cls = getattr(schemas, name)
        if isinstance(cls, type) and issubclass(cls, schemas.BaseSchema) and cls is not schemas.BaseSchema:
            for field_name, field in cls._declared_fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name} has no description"


def test_validation_error_is_raised_by_load():
    with pytest.raises(ValidationError):
        schemas.SearchSchema().load({"fuel": "coal"})
