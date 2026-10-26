"""Marshmallow request schemas for every /autoscout24/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair):

    listing   a listing id (GUID) OR any AutoScout24 offer link, any market host
    dealer    a dealer slug, the numeric customer id OR any dealer page link
    link      an AutoScout24 search results (/lst) link, any market host
    make      a make id (9) OR its name ("Audi"); resolved per vehicle type
    model     a model id (1626) OR its name ("A4"); needs `make`

Coded filters take readable values ("gasoline", "automatic", "4x4") and
map them to the site's own query codes (autoscout24/refs.py, read from the
search funnel bundle and the /lst taxonomy on 2026-10-24); numeric ids
(body type, colour, equipment) come from /autoscout24/taxonomy/filters.
"""
from marshmallow import ValidationError, fields, validate, validates_schema

from autoscout24 import refs
from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LimitField, PageField,
                           PageSizeField, QueryField, RefField, StrippedString)

MAX_SEARCH_PAGE = 200          # 200 x 20 = the site's 4,000-result cap
MAX_PAGE_SIZE = 200
MAX_DEALER_PAGE = 500          # 20 per page; the largest dealers list ~10k vehicles
MAX_REVIEW_PAGE = 500          # 10 per page


def _max_length(n):
    """Length(max=n) that tolerates the None an optional StrippedString
    yields for an empty value (`?make=`): the plain validator would len()
    it into a TypeError that escapes load_query as a bottle 500."""
    return lambda value: value is None or bool(validate.Length(max=n)(value))


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class DealerRefField(RefField):
    resolver = staticmethod(refs.resolve_dealer)


class SearchLinkField(RefField):
    resolver = staticmethod(refs.resolve_search_link)


class IdListField(CommaListField):
    """'4, 6' -> [4, 6]: comma-separated positive integer ids."""

    def __init__(self, max_items=20, **kwargs):
        super().__init__(upper=False, max_items=max_items, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs)
        if items is None:
            return None
        out = []
        for item in items:
            if not item.isdigit() or int(item) < 1:
                raise ValidationError(f"'{item}' is not a numeric id (see /autoscout24/taxonomy/filters).")
            if int(item) not in out:
                out.append(int(item))
        return out


def _int(lo, hi, description):
    return fields.Integer(load_default=None, strict=False, validate=validate.Range(min=lo, max=hi),
                          metadata={"description": description})


def _vehicle_type(default="car"):
    return ChoiceField(refs.VEHICLE_TYPES, load_default=refs.VEHICLE_TYPES[default] if default else None,
                       metadata={"description": "car (default), motorbike, caravan, transporter or trailer"})


def _market_country(default="DE"):
    """One market (no EU-wide value): AT, BE, DE, ES, FR, IT, LU, NL."""
    return ChoiceField(refs.COUNTRIES, load_default=refs.COUNTRIES[default],
                       metadata={"description": "market: AT, BE, DE (default), ES, FR, IT, LU or NL"})


def _check_range(data, low, high):
    if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
        raise ValidationError(f"{low} must not be greater than {high}.", low)


class SearchFiltersSchema(BaseSchema):
    """The filters listings/search and listings/count share."""
    vehicle_type = _vehicle_type()
    country = ChoiceField({**refs.COUNTRIES, refs.EU: refs.EU_CODE}, load_default=refs.COUNTRIES["DE"],
                          metadata={"description": "AT, BE, DE (default), ES, FR, IT, LU, NL, or EU for all eight"})
    make = StrippedString(load_default=None, validate=_max_length(80),
                          metadata={"description": "make id (9) or name (Audi); see /autoscout24/taxonomy/makes"})
    model = StrippedString(load_default=None, validate=_max_length(80),
                           metadata={"description": "model id (1626) or name (A4) of that make; needs make"})
    variant = StrippedString(load_default=None, validate=_max_length(60),
                             metadata={"description": "free-text model version, e.g. gti or avant"})
    keyword = StrippedString(load_default=None, validate=_max_length(100),
                             metadata={"description": "free-text keyword matched against the listing text"})
    price_from = _int(1, 100_000_000, "minimum price in EUR")
    price_to = _int(1, 100_000_000, "maximum price in EUR")
    year_from = _int(1900, 2100, "first registration from this year")
    year_to = _int(1900, 2100, "first registration up to this year")
    mileage_from = _int(0, 10_000_000, "minimum mileage in km")
    mileage_to = _int(0, 10_000_000, "maximum mileage in km")
    power_from = _int(1, 5000, "minimum power, in power_unit")
    power_to = _int(1, 5000, "maximum power, in power_unit")
    power_unit = ChoiceField(refs.POWER_UNITS, load_default="kw",
                             metadata={"description": "unit of power_from / power_to: kw (default) or hp"})
    fuel = CommaListField(value_map=refs.FUELS, metadata={
        "description": "comma list: gasoline, diesel, electric, electric-gasoline, electric-diesel, "
                       "lpg, cng, hydrogen, ethanol, two-stroke, other"})
    transmission = CommaListField(value_map=refs.TRANSMISSIONS, metadata={
        "description": "comma list: automatic, manual, semi-automatic"})
    drivetrain = CommaListField(value_map=refs.DRIVETRAINS, metadata={
        "description": "comma list: 4x4, front, rear"})
    body_type = IdListField(metadata={"description": "comma list of body type ids (taxonomy/filters body_types)"})
    condition = CommaListField(value_map=refs.CONDITIONS, metadata={
        "description": "comma list: new, used, employee-car, classic, demonstration, pre-registered"})
    seller_type = ChoiceField(refs.SELLER_TYPES, metadata={"description": "dealer or private"})
    color = IdListField(metadata={"description": "comma list of body colour ids (taxonomy/filters body_colors)"})
    interior_color = IdListField(metadata={"description": "comma list of interior colour ids"})
    upholstery = CommaListField(value_map=refs.UPHOLSTERY, metadata={
        "description": "comma list: alcantara, cloth, full-leather, part-leather, velour, other"})
    equipment = IdListField(max_items=40, metadata={
        "description": "comma list of equipment ids, all required (taxonomy/filters equipment)"})
    cylinders = CommaListField(value_map=refs.CYLINDERS, metadata={"description": "comma list: 3, 4, 6, 8, 10plus"})
    doors_from = _int(1, 10, "minimum number of doors")
    doors_to = _int(1, 10, "maximum number of doors")
    seats_from = _int(1, 100, "minimum number of seats")
    seats_to = _int(1, 100, "maximum number of seats")
    previous_owners = _int(1, 4, "at most this many previous owners (4 = four or more)")
    emission_class = _int(1, 50, "minimum EU emission class id (taxonomy/filters emission_classes)")
    emission_sticker = _int(1, 5, "minimum German emission sticker (2 red, 3 yellow, 4 green)")
    online_since = _int(1, 14, "listed within this many days")
    electric_range_from = _int(1, 2000, "minimum electric range in km")
    electric_range_to = _int(1, 2000, "maximum electric range in km")
    engine_size_from = _int(1, 20000, "minimum engine displacement in cc")
    engine_size_to = _int(1, 20000, "maximum engine displacement in cc")
    is_vat_deductible = Flag(metadata={"description": "true: only listings with deductible VAT"})
    is_super_deal = Flag(metadata={"description": "true: only listings with a recent price drop"})
    damaged = ChoiceField(refs.DAMAGED, metadata={
        "description": "damaged vehicles: exclude (the site default), include or only"})
    location = StrippedString(load_default=None, validate=_max_length(100),
                              metadata={"description": "postcode or city to search around (see locations/autocomplete)"})
    radius = _int(1, 1000, "search radius around location, in km")

    @validates_schema
    def _consistent(self, data, **kwargs):
        if data.get("model") and not data.get("make"):
            raise ValidationError("model needs a make.", "model")
        if data.get("radius") and not data.get("location"):
            raise ValidationError("radius needs a location.", "radius")
        for low, high in (("price_from", "price_to"), ("year_from", "year_to"), ("mileage_from", "mileage_to"),
                          ("power_from", "power_to"), ("doors_from", "doors_to"), ("seats_from", "seats_to"),
                          ("electric_range_from", "electric_range_to"), ("engine_size_from", "engine_size_to")):
            _check_range(data, low, high)


class SearchSchema(SearchFiltersSchema):
    sort = ChoiceField(refs.SORTS, load_default="standard", metadata={
        "description": "relevance (default), price, newest, mileage, first-registration, power, distance, "
                       "make, finance-rate, leasing-rate"})
    order = ChoiceField(refs.ORDERS, load_default="0", metadata={"description": "asc (default) or desc"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata={"description": "page number (default 1)"})
    page_size = PageSizeField(default=20, max_size=MAX_PAGE_SIZE, metadata={
        "description": "results per page, 1-200 (default 20); the site serves 4,000 results per query at most"})

    @validates_schema
    def _distance_needs_location(self, data, **kwargs):
        if data.get("sort") == "distance" and not data.get("location"):
            raise ValidationError("sort=distance needs a location.", "sort")


class CountSchema(SearchFiltersSchema):
    """listings/count: the search filters, no paging."""


class ByLinkSchema(BaseSchema):
    link = SearchLinkField(metadata={
        "description": "an AutoScout24 search results link (/lst...), from any market site"})
    page = PageField(max_page=MAX_SEARCH_PAGE, load_default=None,
                     metadata={"description": "page number (default: the link's own page, else 1)"})
    page_size = PageSizeField(default=None, max_size=MAX_PAGE_SIZE, load_default=None, metadata={
        "description": "results per page, 1-200 (default: the link's own size, else 20)"})


class ListingSchema(BaseSchema):
    listing = ListingRefField(metadata={
        "description": "listing id (GUID) or an AutoScout24 offer link from any market site"})


class SimilarSchema(ListingSchema):
    limit = LimitField(default=10, max_size=50, metadata={"description": "number of similar listings (default 10, max 50)"})


class DealerSchema(BaseSchema):
    dealer = DealerRefField(metadata={
        "description": "dealer slug, numeric customer id, or an AutoScout24 dealer page link"})


class DealerListingsSchema(DealerSchema):
    vehicle_type = _vehicle_type(default=None)
    make = StrippedString(load_default=None, validate=_max_length(80),
                          metadata={"description": "make id (47) or name (Mercedes-Benz)"})
    model = StrippedString(load_default=None, validate=_max_length(80),
                           metadata={"description": "model id or name of that make; needs make"})
    variant = StrippedString(load_default=None, validate=_max_length(60),
                             metadata={"description": "free-text model version"})
    price_from = _int(1, 100_000_000, "minimum price in EUR")
    price_to = _int(1, 100_000_000, "maximum price in EUR")
    year_from = _int(1900, 2100, "first registration from this year")
    year_to = _int(1900, 2100, "first registration up to this year")
    mileage_from = _int(0, 10_000_000, "minimum mileage in km")
    mileage_to = _int(0, 10_000_000, "maximum mileage in km")
    sort = ChoiceField(refs.DEALER_SORTS, load_default="standard", metadata={
        "description": "relevance (default), price, newest, mileage, first-registration, power"})
    order = ChoiceField(refs.ORDERS, load_default="0", metadata={"description": "asc (default) or desc"})
    page = PageField(max_page=MAX_DEALER_PAGE, metadata={"description": "page number (20 listings per page)"})

    @validates_schema
    def _consistent(self, data, **kwargs):
        if (data.get("model") or data.get("variant")) and not data.get("make"):
            raise ValidationError("model and variant need a make.", "model" if data.get("model") else "variant")
        for low, high in (("price_from", "price_to"), ("year_from", "year_to"), ("mileage_from", "mileage_to")):
            _check_range(data, low, high)


class DealerReviewsSchema(DealerSchema):
    page = PageField(max_page=MAX_REVIEW_PAGE, metadata={"description": "page number (10 reviews per page, newest first)"})


class MakesSchema(BaseSchema):
    vehicle_type = _vehicle_type()
    country = ChoiceField({**refs.COUNTRIES, refs.EU: refs.EU_CODE}, load_default=refs.COUNTRIES["DE"],
                          metadata={"description": "market the listing counts are for (default DE; EU = all)"})


class ModelsSchema(MakesSchema):
    make = StrippedString(required=True, validate=validate.Length(min=1, max=80),
                          metadata={"description": "make id (9) or name (Audi)"})


class TaxonomySearchSchema(BaseSchema):
    query = QueryField(max_length=80, metadata={"description": "make / model text, e.g. golf gti or bmw 3"})
    vehicle_type = _vehicle_type()
    country = _market_country()
    limit = LimitField(default=10, max_size=50, metadata={"description": "number of matches (default 10, max 50)"})


class FiltersSchema(BaseSchema):
    vehicle_type = _vehicle_type()


class LocationsSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "city or postcode prefix, e.g. Berlin or 10115"})
    country = _market_country()
