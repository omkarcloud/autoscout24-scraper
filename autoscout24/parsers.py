"""Pure parsers: raw AutoScout24 page props / JSON -> clean dicts (no I/O).

Every function takes what fetch.py returns and never raises on a partial
payload: a missing or odd field comes back as null (lists as []).

Fixtures (autoscout24/fixtures/, captured 2026-10-24 from www.autoscout24.com
through a German residential exit; the HTML pages are trimmed to their
<title> and __NEXT_DATA__, the only parts the scraper reads):

  search_cars_de_p1.json        /_next/data/.../lst.json?atype=C&cy=D&page=1 (20 cars)
  search_private_de.json        ...&custtype=P (private sellers)
  search_electric_de.json       ...&fuel=E&sort=age&desc=1 (EV / hybrid badges, WLTP chips)
  search_motorbikes_de.json     atype=B (motorbikes)
  search_transporters_de.json   atype=X (vans without a model id)
  search_no_results.json        kwd=zzqxjvwkplm (0 results)
  search_past_end.json          page=201 (past the 4,000-result cap: 0 / 0)
  filters_cars.html             /lst?atype=C&size=1 (the taxonomy in __NEXT_DATA__)
  filters_trailers.html         /lst?atype=L&size=1 (sparse taxonomy: no fuels, no models)
  details_dealer_ev.json        /_next/data/.../details/<guid>.json (dealer, EV, financing)
  details_private_car.json      private seller
  details_motorbike.json        dealer motorbike with an availability date
  details_caravan.json          caravan (no model id, camper specs)
  offer_page.html               HTML /offers/<guid> (the fallback page; full financing overlay)
  not_found.html                the site's "Error Pages" template (HTTP 404 / 403)
  dealer_home.html              /dealerinfo/autoexpo-deutsche-automarkt-gmbh (741 reviews)
  dealer_small_home.html        /dealerinfo/h-und-m-automobile-gmbh (contact persons)
  dealer_list_past_end.html     /dealerinfo/.../list?atype=C&page=999 (0 listings)
  dealer_reviews_skip20.json    POST /api/dealer-detail/fetch-reviews skip=20
  dealer_reviews_past_end.json  skip=5000 -> []
  models_audi.json              /as24-home/api/taxonomy/cars/makes/9/models
  graphql_count_audi.json       counts + facet counters for atype=C&cy=D&mmvmk0=9
  graphql_count_empty.json      the same for a query with no results
  graphql_freetext_golf.json    getFreeTextTaxonomyV2 "golf" (DE)
  locations_berlin.json         location autocomplete DE "Berlin"
  locations_empty.json          IT "zzqxjv" -> []

Fields deliberately dropped (noise for an API client): tracking /
trackingParams / searchTrackingParams / adTargetingString (analytics),
coverImageAttractiveness and imageContent (an internal image score),
headerImage (a 120x90 copy of the first image), imgAltText (the title
again), the flat vehicle fields' "formatted" twins and vehicle.rawData
(the same values again, nested), the financing overlay's legal disclaimer
/ button / tracking texts, ocsInfo (the "buy online" product, always
NotOcs for these listings), togglingInfo / optimizely / interlinking (site
experiments and SEO links), the dealer page's translations and consent
config, seller.dealer package tiers (maxImages, tieredPricingPackage,
autoMatchPackage: the dealer's AutoScout24 plan) and the dealer's sellId
(an internal id that never appears in links).
"""
import html as htmllib
import json
import re
from datetime import datetime, timezone

from autoscout24.refs import (CONDITIONS, COUNTRY_OF_CODE, CYLINDERS, DRIVETRAINS, FUELS, OFFER_TYPE_LABELS,
                              SELLER_TYPES, SITE, SORTS, TRANSMISSIONS, UPHOLSTERY, VEHICLE_TYPE_OF_CODE,
                              absolute, dealer_link, dealer_token_of, listing_link)

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_IMAGE_SIZE_RE = re.compile(r"/\d+x\d+\.(webp|jpg|jpeg|png)$", re.I)
_POWER_RE = re.compile(r"(\d[\d,.]*)\s*kW\s*\((\d[\d,.]*)\s*hp\)", re.I)
_MEASURE_RE = re.compile(r"^\s*(\d[\d.,]*)\s*([^\d(][^(]*?)?\s*(\(comb\.\))?\s*$")
_TAXONOMY_RE = re.compile(r"(make|model_group|variant|generation|motortype|trim)_id:(\d+)")
_CAT_RE = re.compile(r"^ma\d+(?:[a-z]{2}\d+)*$")
_TAG_RE = re.compile(r"<[^>]+>")

# The six dealer rating categories, in the order the site sends them (the
# listing pages label them in the dealer's language: Gesamteindruck,
# Erreichbarkeit, Zuverlässigkeit, Angebotsbeschreibung, Kaufprozess,
# Consultancy; the dealer pages send empty labels).
GRADE_NAMES = ("overall_impression", "availability", "reliability", "offer_description",
               "purchase_process", "consultancy")
# Labels the site sends with a rating category (seen 2026-10-24: German
# for de-DE dealers, "Consultancy" always in English, English on .com).
GRADE_LABELS = {
    "gesamteindruck": "overall_impression", "overall impression": "overall_impression",
    "erreichbarkeit": "availability", "availability": "availability", "accessibility": "availability",
    "zuverlässigkeit": "reliability", "reliability": "reliability",
    "angebotsbeschreibung": "offer_description", "offer description": "offer_description",
    "kaufprozess": "purchase_process", "purchase process": "purchase_process", "buying process": "purchase_process",
    "consultancy": "consultancy", "beratung": "consultancy",
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CURRENCY_SYMBOLS = (("€", "EUR"), ("CHF", "CHF"), ("£", "GBP"), ("zł", "PLN"), ("$", "USD"))
_TYPE_NAMES = {"car": "car", "motorbike": "motorbike", "bike": "motorbike", "caravan": "caravan",
               "transporter": "transporter", "trailer": "trailer"}
# Dealer pages send the offer type as its English label (the /lst taxonomy's
# `offer` labels); mapped back to the codes so `condition` reads the same as
# on search cards and detail pages ("classic", not "antique_/_classic").
_OFFER_LABEL_CODES = {"new": "N", "used": "U", "employee's car": "J", "antique / classic": "O",
                      "demonstration": "D", "pre-registered": "S"}


# ---- page plumbing ------------------------------------------------------------------

def next_data(html):
    """The page's __NEXT_DATA__ JSON, or None."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def page_title(html):
    match = _TITLE_RE.search(html or "")
    return htmllib.unescape(match.group(1)).strip() if match else ""


# ---- value helpers --------------------------------------------------------------------

def _clean(value):
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


def _str(value):
    value = _clean(value)
    return str(value) if value is not None and not isinstance(value, (dict, list)) else None


def _number(value):
    """int / float / "1,968 cc" / "7.60 l/100 km" / "4,8" -> a number, else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    match = re.search(r"\d[\d.,]*", value)
    if not match:
        return None
    token = match.group(0).rstrip(".,")
    if re.fullmatch(r"\d{1,3}(,\d{3})+", token) or re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        return int(re.sub(r"[.,]", "", token))           # 1,577 / 1.577 thousands
    if "," in token and "." not in token:
        token = token.replace(",", ".")                   # 4,8 decimal comma
    token = token.replace(",", "")
    try:
        number = float(token)
    except ValueError:
        return None
    return int(number) if number.is_integer() and "." not in match.group(0) else number


def _int(value):
    number = _number(value)
    return int(round(number)) if number is not None else None


def _amount(formatted):
    """A price string ("€ 12,990,-", "€ 1.890,-", "€ 64,900") -> a number."""
    if not isinstance(formatted, str):
        return _number(formatted)
    text = re.sub(r"[,.]-\s*$", "", formatted.strip())
    digits = re.sub(r"[^\d.,]", "", text)
    if not digits:
        return None
    if re.search(r"[.,]\d{2}$", digits):
        whole, cents = digits[:-3], digits[-2:]
        return float(re.sub(r"[.,]", "", whole) + "." + cents)
    return int(re.sub(r"[.,]", "", digits))


def _currency(formatted):
    if not isinstance(formatted, str) or not formatted.strip():
        return None
    for symbol, code in _CURRENCY_SYMBOLS:
        if symbol in formatted:
            return code
    return "EUR"


def _raw(obj):
    """The `raw` of a {"raw", "formatted"} pair (or the value itself)."""
    if isinstance(obj, dict):
        return obj.get("raw")
    return obj


def _formatted(obj):
    if isinstance(obj, dict):
        value = obj.get("formatted")
        return None if _is_placeholder(value) else _clean(value)
    return None if _is_placeholder(obj) else _clean(obj)


def _is_placeholder(value):
    """The site's empty-value strings: "- (g/km)", "-/-", "- Gear"."""
    return isinstance(value, str) and (value.strip().startswith("-") or not value.strip())


def _month(value):
    """"2021-08-01" / "08/2021" / "10-2007" -> "2021-08" (ISO year-month)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = re.match(r"^(\d{4})-(\d{2})", value)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.match(r"^(\d{1,2})[/.-](\d{4})$", value)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    match = re.match(r"^(\d{4})$", value)
    return value if match else None


def _date(value):
    """"14/01/2027" / "09.10.2026" / "2027-01-14" -> "2027-01-14"."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", value)
    if match:
        return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return None


def _timestamp(value):
    """ISO timestamp with offset -> "YYYY-MM-DDTHH:MM:SSZ" in UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _image(url, size="1280x960"):
    """Listing images ship as 250x188 thumbnails on result cards; the same
    URL serves the full 1280x960 the detail page shows."""
    if not isinstance(url, str) or not url:
        return None
    if "/listing-images/" in url:
        return _IMAGE_SIZE_RE.sub(f"/{size}.webp", url)
    return url


def _picture(url):
    """Dealer picture URLs carry a percent-encoded '>' in their resize spec."""
    return url.replace("%3E", ">") if isinstance(url, str) and url else None


def _snake(name):
    name = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", str(name))
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _measure(text):
    """"7.1 l/100 km (comb.)" -> (7.1, "l/100 km"); placeholders -> (None, None)."""
    if not isinstance(text, str) or _is_placeholder(text):
        return None, None
    match = _MEASURE_RE.match(text)
    if not match:
        return None, None
    unit = (match.group(2) or "").strip() or None
    return _number(match.group(1)), unit


def _flag(value):
    return value if isinstance(value, bool) else None


def html_to_text(fragment):
    """Seller descriptions are HTML (<br />, <ul><li>, <strong>) -> text
    with line breaks and "- " list items."""
    if not isinstance(fragment, str) or not fragment.strip():
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</li>", "", text)
    text = re.sub(r"(?i)</(p|div|ul|ol|h\d|hr)>|<hr\s*/?>", "\n", text)
    text = htmllib.unescape(_TAG_RE.sub("", text))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out, blank = [], False
    for line in lines:
        if not line:
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip() or None


def vehicle_type_name(value):
    """"Car" / "Motorbike" / a code ("B") -> our public vehicle type."""
    if not isinstance(value, str) or not value:
        return None
    if value in VEHICLE_TYPE_OF_CODE:
        return VEHICLE_TYPE_OF_CODE[value]
    return _TYPE_NAMES.get(value.strip().lower())


def _public_value(table, code):
    """The public param value for a site code (FUELS {"gasoline": "B"} -> B -> gasoline)."""
    for name, site_code in table.items():
        if str(site_code) == str(code):
            return name
    return None


def _phones(phones):
    out = []
    for phone in phones or []:
        if not isinstance(phone, dict):
            continue
        number = _clean(phone.get("formattedNumber"))
        if not number:
            continue
        out.append({"type": (_clean(phone.get("phoneType")) or "").lower() or None,
                    "number": number, "e164": _clean(phone.get("callTo"))})
    return out


def _clock(value):
    """900 -> "09:00"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return f"{value // 100:02d}:{value % 100:02d}"


def _opening_hours(entries):
    """[{"department", "timetable": [[900, 1800], ... 7 days]}] -> per
    department, per weekday, the open intervals (an empty list = closed)."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        days = []
        for index, slot in enumerate((entry.get("timetable") or [])[:7]):
            values = [v for v in (slot or []) if isinstance(v, (int, float))]
            intervals = [{"opens": _clock(values[i]), "closes": _clock(values[i + 1])}
                         for i in range(0, len(values) - 1, 2)]
            days.append({"day": WEEKDAYS[index], "is_closed": not intervals, "hours": intervals})
        out.append({"department": _clean(entry.get("department")), "days": days})
    return out


def _grades(grades):
    """Rating categories -> [{"category", "stars"}]. A label the site sends
    names its category; with all six present and unlabelled, the site's
    fixed order names them; otherwise the category stays null (a set of
    five is missing one, and nothing says which)."""
    grades = [g for g in (grades or []) if isinstance(g, dict)]
    out = []
    for index, grade in enumerate(grades):
        label = (_clean(grade.get("label")) or "").lower()
        category = GRADE_LABELS.get(label)
        if category is None and not label and len(grades) == len(GRADE_NAMES):
            category = GRADE_NAMES[index]
        out.append({"category": category, "stars": _number(grade.get("stars"))})
    return out


# ---- search results -----------------------------------------------------------------------

def _chips(details):
    """A result card's spec chips, keyed by icon (the placeholders dropped)."""
    out = {}
    for chip in details or []:
        if not isinstance(chip, dict) or chip.get("isPlaceholder"):
            continue
        data = chip.get("data")
        if _is_placeholder(data):
            continue
        out[chip.get("iconName") or chip.get("name")] = data
    return out


def _power(text):
    match = _POWER_RE.search(text or "")
    if not match:
        return None, None
    return _int(match.group(1)), _int(match.group(2))


def _taxonomy_ids(text):
    """"[make_id:9, model_group_id:1626, variant_id:134, ...];" -> ids."""
    found = {key: int(value) for key, value in _TAXONOMY_RE.findall(text or "")}
    return {
        "make_id": found.get("make"),
        "model_group_id": found.get("model_group"),
        "variant_id": found.get("variant"),
        "generation_id": found.get("generation"),
        "motor_type_id": found.get("motortype"),
        "trim_id": found.get("trim"),
    }


def price_rating(label):
    """The card's price label ("top-price", "toolow-price ", "unknown")."""
    if not isinstance(label, str):
        return None
    label = label.strip().lower()
    if not label or label == "unknown":
        return None
    return label.replace("toolow", "too-low").replace("-", "_")


def _consumption_from(chips, wltp_values):
    texts = [chips.get("water_drop"), chips.get("fuelConsumption")]
    texts += [t for t in (wltp_values or []) if isinstance(t, str) and "/100" in t]
    for text in texts:
        value, unit = _measure(text)
        if value is not None:
            return value, unit
    return None, None


def _co2_from(chips, wltp_values):
    texts = [chips.get("leaf"), chips.get("co2Emission")]
    texts += [t for t in (wltp_values or []) if isinstance(t, str) and "g/km" in t]
    for text in texts:
        value, _ = _measure(text)
        if value is not None:
            return value
    return None


def _search_vehicle(item):
    vehicle = item.get("vehicle") or {}
    tracking = item.get("tracking") or {}
    chips = _chips(item.get("vehicleDetails"))
    power_kw, power_hp = _power(chips.get("speedometer"))
    consumption, unit = _consumption_from(chips, item.get("wltpValues"))
    ids = _taxonomy_ids(tracking.get("modelTaxonomy"))
    beds = chips.get("bed")
    return {
        "type": vehicle_type_name(vehicle.get("type") or vehicle.get("articleType")),
        "make": _clean(vehicle.get("make")),
        "model": _clean(vehicle.get("model")),
        "model_group": _clean(vehicle.get("modelGroup")),
        "variant": _clean(vehicle.get("variant")),
        "version": _clean(vehicle.get("modelVersionInput")) or _clean(vehicle.get("modelVersionCustom")),
        "motor_type": _clean(vehicle.get("motorTypeName")),
        "subtitle": _clean(vehicle.get("subtitle")),
        "condition": OFFER_TYPE_LABELS.get(vehicle.get("offerType")),
        "mileage_km": _int(tracking.get("mileage")) if tracking.get("mileage") else _int(vehicle.get("mileageInKm")),
        "first_registration": _month(tracking.get("firstRegistration")) or _month(chips.get("calendar")),
        "fuel": _clean(vehicle.get("fuel")) if not _is_placeholder(vehicle.get("fuel")) else None,
        "transmission": None if _is_placeholder(vehicle.get("transmission")) else _clean(vehicle.get("transmission")),
        "power_kw": power_kw,
        "power_hp": power_hp,
        "engine_displacement_cc": _int(vehicle.get("engineDisplacementInCCM")),
        "fuel_consumption": consumption,
        "fuel_consumption_unit": unit,
        "co2_emissions_g_per_km": _co2_from(chips, item.get("wltpValues")),
        "gross_weight_kg": _int(chips.get("gross_weight")),
        "beds": _int(beds) if isinstance(beds, str) else None,
        "electrification": _clean((item.get("evBanner") or {}).get("type")),
        "is_damaged": _flag(vehicle.get("isCurrentlyDamaged")),
        "make_id": ids["make_id"],
        "model_id": _int(vehicle.get("modelId")),
        "model_group_id": ids["model_group_id"],
        "variant_id": ids["variant_id"],
        "generation_id": ids["generation_id"],
        "motor_type_id": ids["motor_type_id"],
        "trim_id": ids["trim_id"],
    }


def _search_seller(seller, ratings):
    seller = seller or {}
    is_dealer = seller.get("type") == "Dealer"
    links = seller.get("links") or {}
    info = links.get("infoPage")
    slug = dealer_token_of(info) if is_dealer else None
    ratings = ratings or {}
    rating = None
    if ratings.get("ratingsEnabled") or ratings.get("ratingsCount"):
        rating = {"count": _int(ratings.get("ratingsCount")), "stars": _number(ratings.get("ratingsStars"))}
    return {
        "id": _str(seller.get("id")),
        "type": "dealer" if is_dealer else ("private" if seller.get("type") else None),
        "name": _clean(seller.get("companyName")),
        "contact_name": _clean(seller.get("contactName")),
        "slug": slug,
        "link": dealer_link(slug) if slug else None,
        "listings_link": absolute(info),
        "imprint_link": absolute(links.get("imprint")),
        "logo": _picture(((seller.get("logo") or {}).get("small") or {}).get("href")),
        "language": _clean((seller.get("dealer") or {}).get("culture")),
        "phones": _phones(seller.get("phones")),
        "rating": rating,
    }


def parse_search_listing(item):
    """One result card of a /lst page -> a listing summary."""
    if not isinstance(item, dict) or not item.get("id"):
        return None
    guid = str(item["id"]).lower()
    price = item.get("price") or {}
    superscripts = [s.strip() for s in str(price.get("priceSuperscriptString") or "").split(",")]
    super_deal = item.get("superDeal") or {}
    availability = item.get("availability") or {}
    location = item.get("location") or {}
    images = [_image(u) for u in item.get("images") or [] if isinstance(u, str)]
    return {
        "id": guid,
        "title": _clean(item.get("title")),
        "link": absolute(item.get("url")) or listing_link(guid),
        "price": {
            "amount": _number(price.get("priceRaw")) if price.get("priceRaw") is not None
            else _amount(price.get("priceFormatted")),
            "currency": _currency(price.get("priceFormatted")),
            # footnote 1 on a price is the site's "VAT deductible" label
            "is_vat_deductible": "1" in superscripts,
            "is_conditional": bool(price.get("isConditionalPrice")),
            "previous_amount": _amount(super_deal.get("oldPriceFormatted")) if super_deal.get("isEligible") else None,
            "suggested_retail_price": _amount(price.get("suggestedRetailPrice")),
            "rating": price_rating((item.get("tracking") or {}).get("priceLabel")),
        },
        "vehicle": _search_vehicle(item),
        "images": [u for u in images if u],
        "image_count": len(images),
        "has_video": bool(item.get("hasVideo")),
        "has_360_view": bool(item.get("has360Image")),
        "location": {
            "country_code": _clean(location.get("countryCode")),
            "zip": _clean(location.get("zip")),
            "city": _clean(location.get("city")),
            "street": _clean(location.get("street")),
        },
        "seller": _search_seller(item.get("seller"), item.get("ratings")),
        "is_new_listing": bool(item.get("isOfferNew")),
        "is_available_now": _flag(item.get("availableNow")),
        "available_from": _date(availability.get("fromDate")),
        "available_in_days": _int(availability.get("inDays")),
        "is_super_deal": bool(super_deal.get("isEligible")),
        "is_boosted": bool(item.get("isListingBoost")),
        "leads_range": (_clean((item.get("statistics") or {}).get("leadsRange")) or "").lower() or None,
        "ad_tier": _clean(item.get("adTier")),
        "result_type": (_clean(item.get("searchResultType")) or "").lower() or None,
    }


def parse_search(props):
    """/lst page props -> {"results", "total_count", "total_pages", "query"}.
    total_pages is the site's own (capped at 4,000 reachable results); a
    page past the cap or the end reports 0 / 0 (callers handle that)."""
    props = props or {}
    results = [r for r in (parse_search_listing(i) for i in props.get("listings") or []) if r]
    query = props.get("pageQuery") if isinstance(props.get("pageQuery"), dict) else {}
    return {
        "results": results,
        "total_count": _int(props.get("numberOfResults")),
        "total_pages": _int(props.get("numberOfPages")),
        "query": {str(k): str(v) for k, v in query.items() if v is not None},
    }


# ---- listing details --------------------------------------------------------------------------

_SPEC_FIELDS = (
    "engineHours", "fuelDeliveryType", "engineCoolingSystem", "slideOutCount", "chassisManufacturerName",
    "exteriorMaterial", "extendedLength", "flooringMaterial", "fridgePowerType", "fridgeCapacity",
    "waterTankCapacity", "wasteTankCapacity", "engineManufacturerName", "axleSpread", "brakeType",
    "cabinAxleDistance", "differentialRatio", "frameType", "rearAxleWeightRating", "frontAxleWeightRating",
    "trackDimension", "skiStanceWidth", "fuelCapacity", "headCount", "hullMaterial", "steeringType",
    "auxiliaryPower", "engineMountingType", "engineCount", "controlModuleName", "marketingDescription",
)


def _equipment(vehicle):
    equipment = vehicle.get("equipment") or {}
    out = {}
    for category, items in equipment.items():
        names = [_clean(i.get("id")) for i in items or [] if isinstance(i, dict) and _clean(i.get("id"))]
        if names:
            out[_snake(category)] = names
    ids = []
    for item in ((vehicle.get("rawData") or {}).get("equipment") or {}).get("as24") or []:
        raw = ((item or {}).get("id") or {}).get("raw")
        if isinstance(raw, int) and raw not in ids:
            ids.append(raw)
    return out, ids


def _wltp(wltp):
    out = {}
    for key, value in (wltp or {}).items():
        raw = _raw(value)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            out[_snake(key.replace("WithFallback", ""))] = raw
    return out or None


def _details_vehicle(vehicle, ld):
    classification = ((vehicle.get("rawData") or {}).get("classification") or {})
    condition_raw = ((vehicle.get("rawData") or {}).get("condition") or {})
    damage = condition_raw.get("damage") or {}
    group_ids = [g for g in vehicle.get("modelGroupIds") or [] if isinstance(g, int)]
    equipment, equipment_ids = _equipment(vehicle)
    consumption_unit = _measure(_formatted(vehicle.get("fuelConsumptionCombined")) or "")[1]
    if consumption_unit is None:
        unit = re.search(r"\(([^)]+)\)", (vehicle.get("fuelConsumptionCombined") or {}).get("formatted") or "")
        consumption_unit = unit.group(1) if unit else None
    electric_range = vehicle.get("electricRangeWithFallback") or {}
    specs = {}
    for key in _SPEC_FIELDS:
        value = vehicle.get(key)
        if value not in (None, "", [], {}, False):
            specs[_snake(key)] = value
    return {
        "type": vehicle_type_name(vehicle.get("type") or ld.get("articleType")),
        "make": _clean(vehicle.get("make")),
        "model": _clean(vehicle.get("model")),
        "model_group": _clean(vehicle.get("modelGroup")),
        "variant": _clean(vehicle.get("variant")),
        "version": _clean(vehicle.get("modelVersionInput")),
        "custom_version": _clean(vehicle.get("modelVersionCustom")),
        "motor_type": _clean(vehicle.get("motorTypeName")),
        "generation": _formatted(classification.get("modelGeneration")),
        "condition": OFFER_TYPE_LABELS.get(vehicle.get("offerType")),
        "legal_categories": [c for c in (_clean(x) for x in vehicle.get("legalCategories") or []) if c],
        "mileage_km": _int(vehicle.get("mileageInKmRaw")),
        "first_registration": _month(vehicle.get("firstRegistrationDateRaw") or vehicle.get("firstRegistrationDate")),
        "production_year": _int(vehicle.get("productionYear")),
        "previous_owners": _int(vehicle.get("noOfPreviousOwners")),
        "history": {
            "had_accident": _flag(vehicle.get("hadAccident")),
            "is_accident_free": _flag(damage.get("accidentFree")),
            "is_roadworthy": _flag(damage.get("isRoadworthy")),
            "damage_conditions": [d for d in (_clean(x) if isinstance(x, str) else _formatted(x)
                                              for x in vehicle.get("damageConditions") or []) if d],
            "is_non_smoking": _flag(vehicle.get("nonSmoking")),
            "has_full_service_history": _flag(vehicle.get("hasFullServiceHistory")),
            "last_service": _month(vehicle.get("lastTechnicalServiceDate")),
            "last_timing_belt_service": _month(vehicle.get("lastBeltServiceDate")),
            "next_inspection": _month(vehicle.get("nextVehicleSafetyInspection")),
            "has_new_inspection": _flag(vehicle.get("newInspection")),
            "is_rental": _flag(vehicle.get("isRental")),
            "is_new_driver_suitable": _flag(vehicle.get("newDriverSuitable")),
            "original_market": _clean(vehicle.get("originalMarket")),
        },
        "body": {
            "body_type": _clean(vehicle.get("bodyType")),
            "color": _clean(vehicle.get("bodyColor")),
            "manufacturer_color": _clean(vehicle.get("bodyColorOriginal")),
            "paint": _clean(vehicle.get("paintType")),
            "doors": _int(vehicle.get("numberOfDoors")),
            "seats": _int(vehicle.get("numberOfSeats")),
            "upholstery": _clean(vehicle.get("upholstery")),
            "upholstery_color": _clean(vehicle.get("upholsteryColor")),
        },
        "engine": {
            "power_kw": _int(vehicle.get("rawPowerInKw")) if vehicle.get("rawPowerInKw") is not None
            else _int(vehicle.get("powerInKw")),
            "power_hp": _int(vehicle.get("rawPowerInHp")) if vehicle.get("rawPowerInHp") is not None
            else _int(vehicle.get("powerInHp")),
            "transmission": _clean(vehicle.get("transmissionType")),
            "gears": _int(vehicle.get("gears")),
            "cylinders": _int(vehicle.get("cylinders")),
            "displacement_cc": _int(vehicle.get("rawDisplacementInCCM")) or _int(vehicle.get("rawCylinderCapacity"))
            or _int(vehicle.get("displacementInCCM")),
            "drivetrain": _clean(vehicle.get("driveTrain")),
            "empty_weight_kg": _int(vehicle.get("weight")),
            "has_particle_filter": _flag(vehicle.get("hasParticleFilter")),
        },
        "fuel": {
            "category": _formatted(vehicle.get("fuelCategory")),
            "primary": _formatted(vehicle.get("primaryFuel")),
            "additional": [f for f in (_formatted(x) for x in vehicle.get("additionalFuel") or []) if f],
            "powertrain": _clean(ld.get("vehicleType")),
            "consumption_combined": _raw(vehicle.get("fuelConsumptionCombined")),
            "consumption_urban": _raw(vehicle.get("fuelConsumptionUrban")),
            "consumption_extra_urban": _raw(vehicle.get("fuelConsumptionExtraUrban")),
            "consumption_unit": consumption_unit,
            "co2_emissions_g_per_km": _raw(vehicle.get("co2emissionInGramPerKmWithFallback")),
            "electric_range_km": _int(_raw(electric_range)),
            "is_electric_range_estimated": _flag(electric_range.get("isFallback")) if _raw(electric_range) is not None else None,
            "electric_range_city_km": _int(_raw(vehicle.get("electricRangeCity"))),
            "battery_ownership": _formatted(vehicle.get("batteryOwnershipType")),
            "battery_charging_time": _formatted(vehicle.get("batteryChargingTime")),
            "wltp": _wltp(vehicle.get("wltp")),
        },
        "environment": {
            "emission_class": _formatted(vehicle.get("environmentEuDirective")),
            "emission_sticker": _formatted(vehicle.get("environmentBImSchV35")),
            "co2_class": _formatted(vehicle.get("environmentPkwEnVKV")),
        },
        "dimensions": {
            "length_mm": _int(vehicle.get("totalLength")),
            "width_mm": _int(vehicle.get("totalWidth")),
            "height_mm": _int(vehicle.get("totalHeight")),
            "wheelbase_mm": _int(vehicle.get("wheelBase")),
            "gross_weight_kg": _int(vehicle.get("grossVehicleWeight")),
            "payload_kg": _int(vehicle.get("payload")),
            "max_towing_weight_kg": _int(vehicle.get("maximumTowingWeight")),
            "load_length_mm": _int(vehicle.get("loadLength")),
            "load_width_mm": _int(vehicle.get("loadWidth")),
            "load_height_mm": _int(vehicle.get("loadHeight")),
            "load_volume": _clean(vehicle.get("loadVolume")),
            "axles": _int(vehicle.get("numberOfAxles")),
            "beds": _int(vehicle.get("numberOfBeds")),
        },
        "specs": specs,
        "equipment": equipment,
        "equipment_ids": equipment_ids,
        "hsn_tsn": _clean(vehicle.get("hsnTsn")),
        "license_plate": _clean(vehicle.get("licensePlate")),
        "make_id": _int(vehicle.get("makeId")),
        "model_id": _int(vehicle.get("modelId")),
        "model_group_id": group_ids[0] if group_ids else None,
        "generation_id": _int(vehicle.get("modelGenerationId")),
        "variant_id": _int(vehicle.get("modelVariantId")),
        "motor_type_id": _int(vehicle.get("motorTypeId")),
        "trim_id": _int(vehicle.get("trimLineId")),
    }


def _details_price(ld):
    prices = ld.get("prices") or {}
    public = prices.get("public") or {}
    dealer = prices.get("dealer") or {}
    price = ld.get("price") or {}
    super_deal = ld.get("superDeal") or {}
    amount = _number(public.get("priceRaw")) if public.get("priceRaw") is not None else _amount(public.get("price"))
    dealer_amount = _number(dealer.get("priceRaw"))
    evaluation = None
    if public.get("category") or public.get("median") or public.get("evaluationRanges"):
        evaluation = {"category": _clean(public.get("category")), "median": _number(public.get("median")),
                      "ranges": public.get("evaluationRanges")}
    suggested = prices.get("suggestedRetail")
    return {
        "amount": amount,
        "currency": _currency(public.get("price") or price.get("priceFormatted")),
        "net_amount": _number(public.get("netPriceRaw")),
        "vat_rate": _number(public.get("vatRate")),
        "is_vat_deductible": _flag(public.get("taxDeductible")),
        "is_negotiable": _flag(public.get("negotiable")),
        "is_on_request": _flag(public.get("onRequestOnly")),
        "is_final": _flag(prices.get("isFinalPrice")),
        "is_conditional": bool(price.get("isConditionalPrice")),
        "dealer_amount": dealer_amount if dealer_amount is not None and dealer_amount != amount else None,
        "previous_amount": _amount(super_deal.get("oldPriceFormatted")) if super_deal.get("isEligible") else None,
        "suggested_retail_price": _amount(suggested.get("price") if isinstance(suggested, dict) else suggested),
        "evaluation": evaluation,
    }


def _rating_block(ratings):
    ratings = ratings or {}
    if not (ratings.get("ratingsCount") or ratings.get("ratingsStars")):
        return None
    return {
        "count": _int(ratings.get("ratingsCount")),
        "stars": _number(ratings.get("ratingsStars")),
        "average": _number(ratings.get("ratingsAverage")),
        "recommend_percentage": _int(ratings.get("recommendPercentage")),
        "categories": _grades(ratings.get("ratingsByCategory")),
        "link": absolute(ratings.get("urlName")),
    }


def _details_seller(ld):
    seller = ld.get("seller") or {}
    dealer = seller.get("dealer") or {}
    links = seller.get("links") or {}
    is_dealer = seller.get("type") == "Dealer" or bool(seller.get("isDealer"))
    slug = dealer_token_of(links.get("infoPage")) or dealer_token_of(links.get("stockLink")) if is_dealer else None
    logo = seller.get("logo") or {}
    hours = dealer.get("openingHours") or {}
    pictures = ((dealer.get("superbranding") or {}).get("images")) or {}
    google = dealer.get("googleRatings") if isinstance(dealer.get("googleRatings"), dict) else None
    seller_id = _str(seller.get("id"))
    listings_link = absolute(links.get("stockLink"))
    if not listings_link and not is_dealer and seller_id and seller_id != "0":
        # A private seller's other listings: the result cards link a
        # customer-id search (/lst?atype=C&cid=<id>); the detail page does not.
        type_code = {v: k for k, v in VEHICLE_TYPE_OF_CODE.items()}.get(
            vehicle_type_name((ld.get("vehicle") or {}).get("type")) or "car", "C")
        listings_link = f"{SITE}/lst?atype={type_code}&cid={seller_id}"
    return {
        "id": seller_id,
        "type": "dealer" if is_dealer else ("private" if seller.get("type") else None),
        "name": _clean(seller.get("companyName")),
        "contact_name": _clean(seller.get("contactName")),
        "slug": slug,
        "link": dealer_link(slug) if slug else None,
        "listings_link": listings_link,
        "imprint_link": absolute(links.get("imprint")),
        "homepage": _clean(dealer.get("homepageUrl")),
        "logo": _picture(((logo.get("big") or logo.get("small")) or {}).get("href")),
        "images": {
            "exterior": _picture(pictures.get("dealershipExterior")),
            "interior": _picture(pictures.get("dealershipInterior")),
        },
        "phones": _phones(seller.get("phones")),
        "whatsapp": _clean(ld.get("whatsappNumber")),
        "language": _clean(dealer.get("culture")),
        "customer_since": _int(dealer.get("customerSince")),
        "is_best_priced_dealer": _flag(dealer.get("isBestPricedDealer")),
        "opening_status": {
            "state": _clean(hours.get("state")),
            "label": _clean(hours.get("statusLabel")),
            "info": _clean(hours.get("infoLabel")),
        } if hours else None,
        "opening_hours": _opening_hours(dealer.get("openingHoursRaw")),
        "rating": _rating_block(ld.get("ratings")),
        "google_rating": {_snake(k): v for k, v in google.items()} if google else None,
    }


def _financing(entries):
    out, seen = [], set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        provider = _clean(entry.get("productType"))
        if provider in seen:
            continue
        seen.add(provider)
        overlay = entry.get("overlay") or {}
        stage = entry.get("stage") or {}
        offering = overlay.get("proxyOffering") or {}
        rate = _raw(overlay.get("rate")) if overlay.get("rate") else stage.get("rate")
        out.append({
            "provider": provider,
            "monthly_rate": round(rate, 2) if isinstance(rate, (int, float)) else None,
            "duration_months": _int(_raw(overlay.get("duration"))) or _int(offering.get("duration")),
            "down_payment": _number(_raw(overlay.get("deposit"))),
            "net_loan": _number(_raw(overlay.get("creditAmount"))),
            "total_amount": round(_raw(overlay.get("totalAmount")), 2)
            if isinstance(_raw(overlay.get("totalAmount")), (int, float)) else None,
            "effective_interest_rate": _number(_raw(overlay.get("interest"))),
            "borrowing_rate": _number(_raw(overlay.get("debitInterest"))),
            "final_installment": _amount((overlay.get("balloon") or {}).get("formatted")),
            "bank": _clean(offering.get("bankName")),
            "link": _clean(((stage.get("link") or {}).get("url"))),
        })
    return out


def _insurance(entries):
    out, seen = [], set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        provider = _clean(entry.get("productType"))
        if provider in seen:
            continue
        seen.add(provider)
        overlay = entry.get("overlay") or {}
        stage = entry.get("stage") or {}
        out.append({
            "provider": provider,
            "liability_monthly": _number(_raw(overlay.get("automobileLiability"))) or _number(stage.get("rate")),
            "partial_cover_monthly": _number(_raw(overlay.get("partiallyComprehensive"))),
            "comprehensive_monthly": _number(_raw(overlay.get("fullyComprehensive"))),
            "link": _clean(((stage.get("link") or {}).get("url"))),
        })
    return out


def _history_report(ld):
    for partner in ld.get("partnerIntegrations") or []:
        if isinstance(partner, dict) and partner.get("partnerUrl"):
            carfax = ((ld.get("vehicleReport") or {}).get("carfax") or {})
            return {"provider": _clean(partner.get("partnerName")), "link": partner.get("partnerUrl"),
                    "is_free": carfax.get("carfaxMode") == "FreeCarFax" if carfax else None}
    return None


def _leasing(details):
    if not isinstance(details, dict) or not details:
        return None

    def walk(value):
        if isinstance(value, dict):
            return {_snake(k): walk(v) for k, v in value.items()
                    if k != "__typename" and v not in (None, "", [], {})}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value
    return walk(details)


def parse_listing(props):
    """Detail page props (data route or HTML) -> the full listing record."""
    ld = (props or {}).get("listingDetails") or {}
    guid = str(ld.get("id") or "").lower() or None
    vehicle = ld.get("vehicle") or {}
    location = ld.get("location") or {}
    identifier = ld.get("identifier") or {}
    availability = ld.get("availability") or {}
    financing = ld.get("financingAndInsurance") or {}
    images = [_image(u) for u in ld.get("images") or [] if isinstance(u, str)]
    description_html = ld.get("description") if isinstance(ld.get("description"), str) else None
    warranty = ld.get("warranty")
    return {
        "id": guid,
        "title": _clean(ld.get("title")),
        "link": _clean(ld.get("webPage")) or (listing_link(guid) if guid else None),
        "status": (_clean(ld.get("status")) or "").lower() or None,
        "price": _details_price(ld),
        "vehicle": _details_vehicle(vehicle, ld),
        "description": html_to_text(description_html),
        "description_html": _clean(description_html) and description_html.strip(),
        "images": [u for u in images if u],
        "image_count": len(images),
        "video_link": _clean(ld.get("youtubeLink")),
        "view_360_link": _clean(ld.get("twinnerUrl")),
        "has_360_view": bool(ld.get("hasThreeSixtyContent")),
        "location": {
            "country_code": _clean(location.get("countryCode")),
            "zip": _clean(location.get("zip")),
            "city": _clean(location.get("city")),
            "street": _clean(location.get("street")),
            "latitude": _number(location.get("latitude")),
            "longitude": _number(location.get("longitude")),
        },
        "seller": _details_seller(ld),
        "warranty": _clean(warranty) if isinstance(warranty, str) else (_leasing(warranty) if warranty else None),
        "has_warranty": bool(ld.get("warrantyExists")) or bool(warranty),
        "leasing": _leasing(ld.get("leasingDetails")),
        "financing": _financing(financing.get("buttonWithFinance")),
        "insurance": _insurance(financing.get("buttonWithInsurance")),
        "history_report": _history_report(ld),
        "identifiers": {
            "offer_reference": _str(identifier.get("offerReference")),
            "legacy_id": _str(identifier.get("legacyId")),
            "cross_reference_id": _str(identifier.get("crossReferenceId")),
        },
        "is_new_listing": bool(ld.get("isNew")),
        "available_from": _date(availability.get("rawFromDate") or availability.get("fromDate")),
        "available_in_days": _int(availability.get("inDays")),
        "is_available_now": not (availability.get("rawFromDate") or availability.get("fromDate")
                                 or availability.get("inDays")),
        "is_super_deal": bool((ld.get("superDeal") or {}).get("isEligible")),
        "special_conditions": [c for c in (_str(x) if not isinstance(x, dict) else _clean(x.get("label") or x.get("name"))
                                           for x in ld.get("specialConditions") or []) if c],
        "leads_range": (_clean((ld.get("statistics") or {}).get("leadsRange")) or "").lower() or None,
        "ad_tier": _clean(ld.get("adTier")),
        "created_at": _timestamp(ld.get("createdTimestampWithOffset")),
    }


# ---- dealers -----------------------------------------------------------------------------------

def parse_review(review):
    if not isinstance(review, dict):
        return None
    reply = _clean(review.get("replyText"))
    return {
        "id": _str(review.get("reviewId")),
        "rating": _number(review.get("stars")),
        "date": _date(review.get("created")),
        "author": _clean(review.get("name")),
        "text": (review.get("reviewText") or "").strip() or None,
        "grades": _grades(review.get("grades")),
        "reply": {"text": reply, "date": _date(review.get("replyCreated"))} if reply else None,
        "is_top_rating": bool(review.get("topRating")),
    }


def parse_reviews(payload):
    return [r for r in (parse_review(x) for x in payload or []) if r]


def parse_dealer_listing(item):
    """One listing on a dealer page (a different shape from search cards)."""
    if not isinstance(item, dict) or not item.get("id"):
        return None
    guid = str(item["id"]).lower()
    vehicle = item.get("vehicle") or {}
    public = ((item.get("prices") or {}).get("public")) or {}
    dealer_price = ((item.get("prices") or {}).get("dealer")) or {}
    super_deal = item.get("superDeal") or {}
    offer = [o for o in vehicle.get("offerType") or [] if isinstance(o, str)]
    make, model = _clean(vehicle.get("make")), _clean(vehicle.get("model"))
    images = [_image(u) for u in item.get("images") or [] if isinstance(u, str)]
    amount = _number(public.get("priceRaw"))
    dealer_amount = _number(dealer_price.get("priceRaw"))
    leasing = None
    if item.get("monthlyRateGross") or item.get("monthlyRateNet") or item.get("duration"):
        leasing = {"monthly_rate_gross": _amount(item.get("monthlyRateGross")),
                   "monthly_rate_net": _amount(item.get("monthlyRateNet")),
                   "duration_months": _int(item.get("duration"))}
    consumption = vehicle.get("fuelConsumptionCombinedWithFallback") or {}
    return {
        "id": guid,
        "title": " ".join(p for p in (make, model) if p) or None,
        "link": absolute(item.get("url")) or listing_link(guid),
        "price": {
            "amount": amount,
            "currency": _currency(public.get("price")),
            "net_amount": _number(public.get("netPriceRaw")),
            "vat_rate": _number(public.get("vatRate")),
            "is_vat_deductible": _flag(public.get("taxDeductible")),
            "dealer_amount": dealer_amount if dealer_amount is not None and dealer_amount != amount else None,
            "previous_amount": _amount(super_deal.get("oldPriceFormatted")) if super_deal.get("isEligible") else None,
        },
        "vehicle": {
            "type": vehicle_type_name(vehicle.get("articleType")),
            "make": make,
            "model": model,
            "version": _clean(vehicle.get("modelVersionInput")),
            "subtitle": _clean(vehicle.get("subtitle")),
            "condition": (OFFER_TYPE_LABELS.get(_OFFER_LABEL_CODES.get(offer[0].strip().lower()))
                          or offer[0].lower().replace(" ", "_")) if offer else None,
            "body_type": _formatted(vehicle.get("bodyType")),
            "mileage_km": _int(_raw(vehicle.get("mileageInKm"))),
            "first_registration": _month(_raw(vehicle.get("firstRegistrationDate"))),
            "previous_owners": _int(_raw(vehicle.get("noOfPreviousOwners"))),
            "fuel": _formatted(vehicle.get("fuelCategory")),
            "primary_fuel": _formatted(vehicle.get("primaryFuel")),
            "additional_fuels": [f for f in (_formatted(x) for x in vehicle.get("additionalFuel") or []) if f],
            "transmission": _formatted(vehicle.get("transmissionType")),
            "power_kw": _int(_raw(vehicle.get("powerInKw"))),
            "power_hp": _int(_raw(vehicle.get("powerInHp"))),
            "fuel_consumption": _raw(consumption),
            "fuel_consumption_unit": _measure(consumption.get("formatted"))[1] if consumption.get("formatted") else None,
            "electric_consumption": _raw(vehicle.get("fuelConsumptionElectricCombinedWithFallback")),
            "co2_emissions_g_per_km": _raw(vehicle.get("co2emissionWithFallback")),
            "co2_class": _formatted(vehicle.get("co2ClassWithFallback")),
            "electric_range_km": _int(_raw(vehicle.get("electricRangeWithFallback"))),
        },
        "images": [u for u in images if u],
        "image_count": len(images),
        "has_360_view": bool(item.get("has360Image")),
        "is_super_deal": bool(super_deal.get("isEligible")),
        "leasing": leasing,
        "seals": [s for s in (_str(x) if not isinstance(x, dict) else _clean(x.get("name") or x.get("label"))
                              for x in item.get("seals") or []) if s],
        "location": {"country_code": _clean((item.get("location") or {}).get("countryCode"))},
    }


def _dealer_rating(ratings):
    ratings = ratings or {}
    if not (ratings.get("ratingCount") or ratings.get("reviewCount")):
        return None
    return {
        "count": _int(ratings.get("ratingCount")),
        "review_count": _int(ratings.get("reviewCount")),
        "average": _number(ratings.get("ratingAverage")),
        "stars": _number(ratings.get("ratingStars")),
        "recommend_percentage": _int(ratings.get("recommendPercentage")),
        "categories": _grades(ratings.get("gradesAverage")),
    }


def parse_dealer_page(props):
    """A dealer page's props -> the dealer record with its first listings
    page and its 10 newest reviews."""
    props = props or {}
    page = props.get("dealerInfoPage") or {}
    address = page.get("customerAddress") or {}
    slug = _clean(page.get("slug")) or _clean(props.get("slug"))
    shown = page.get("customerPhoneNumbers") or []
    dial = page.get("callPhoneNumbers") or []
    phones = []
    for index, number in enumerate(shown):
        if _clean(number):
            phones.append({"number": _clean(number),
                           "e164": _clean(dial[index]) if index < len(dial) else None})
    hero = page.get("heroImage") or {}
    logo = page.get("logo") or {}
    ratings = page.get("ratings") or {}
    listings = [r for r in (parse_dealer_listing(i) for i in props.get("listings") or []) if r]
    rating = _dealer_rating(ratings)
    return {
        "id": _int(page.get("customerId")) if page.get("customerId") is not None else _int(props.get("customerId")),
        "slug": slug,
        "name": _clean(page.get("customerName")),
        "link": dealer_link(slug),
        "contact_name": _clean(page.get("contactName")),
        "company_add_on": _clean(page.get("companyAddOn")),
        "about": (page.get("aboutUs") or "").strip() or None,
        "services": [s for s in (_clean((x or {}).get("name")) if isinstance(x, dict) else _str(x)
                                 for x in page.get("additionalServices") or []) if s],
        "dealer_types": [t for t in (_clean((x or {}).get("name")) if isinstance(x, dict) else _str(x)
                                     for x in page.get("dealerTypes") or []) if t],
        "rating": rating,
        "listings_count": _int(props.get("numberOfResults")),
        "reviews_count": (rating or {}).get("review_count") or 0,
        "address": {
            "street": _clean(address.get("street")),
            "zip": _clean(address.get("zipCode")),
            "city": _clean(address.get("city")),
            "country_code": _clean(address.get("country")),
        },
        "phones": phones,
        "fax_numbers": [f for f in (_clean(x) for x in page.get("customerFaxNumbers") or []) if f],
        "homepage": _clean(page.get("homepageUrl")),
        "opening_hours": _opening_hours(page.get("openingHours")),
        "contact_persons": [{"name": _clean(p.get("name")), "position": _clean(p.get("position"))}
                            for p in page.get("contactPersons") or [] if isinstance(p, dict)],
        "branches": [b for b in (_leasing(x) if isinstance(x, dict) else _str(x)
                                 for x in page.get("branches") or []) if b],
        "logo": _picture(logo.get("url") or logo.get("small")),
        "hero_image": _picture(hero.get("big") or hero.get("url") or hero.get("medium")),
        "imprint": (page.get("imprint") or "").strip() or None,
        "language": _clean(page.get("culture")),
        "default_vehicle_type": vehicle_type_name(props.get("defaultVehicleType")),
        "listings": listings,
        "reviews": parse_reviews(ratings.get("reviews")),
    }


# ---- taxonomy / counts / places ---------------------------------------------------------------

def _options(entries, key="id"):
    out = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("value") is not None:
            out.append({key: entry.get("value"), "name": _clean(str(entry.get("label")))})
    return out


def _coded(entries, table):
    """Site-coded options -> {"value" (the search param), "code", "name"}."""
    out = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("value") is not None:
            code = str(entry.get("value"))
            out.append({"value": _public_value(table, code), "code": code, "name": _clean(str(entry.get("label")))})
    return out


def _plain(values):
    return [v if not isinstance(v, dict) else v.get("value") for v in values or []
            if (v.get("value") if isinstance(v, dict) else v) is not None]


def parse_makes(taxonomy):
    """[{"id", "name", "is_top_make"}] in the site's alphabetical order."""
    taxonomy = taxonomy or {}
    top = set(taxonomy.get("topMakeIds") or [])
    ordered = taxonomy.get("makesSorted") or list((taxonomy.get("makes") or {}).values())
    out = []
    for entry in ordered:
        if isinstance(entry, dict) and isinstance(entry.get("value"), int):
            out.append({"id": entry["value"], "name": _clean(entry.get("label")), "is_top_make": entry["value"] in top})
    return out


def parse_filters(taxonomy):
    """The /lst taxonomy -> every filter list a search can use."""
    t = taxonomy or {}
    countries = []
    for entry in t.get("country") or []:
        if isinstance(entry, dict):
            iso = "EU" if entry.get("value") == "A,B,D,E,F,I,L,NL" else COUNTRY_OF_CODE.get(entry.get("value"))
            countries.append({"value": iso, "code": entry.get("value"), "name": _clean(entry.get("label"))})
    sorts = []
    for entry in t.get("sortingKeys") or []:
        if isinstance(entry, dict):
            sorts.append({"value": _public_value(SORTS, entry.get("value")), "code": entry.get("value"),
                          "name": _clean(entry.get("label"))})
    years = [y for y in t.get("firstRegistrationFrom") or [] if isinstance(y, int)]
    return {
        "body_types": _options(t.get("bodyType")),
        "fuel_types": _coded(t.get("fuelType"), FUELS),
        "transmissions": _coded(t.get("gearing"), TRANSMISSIONS),
        "drivetrains": _coded(t.get("drivetrain"), DRIVETRAINS),
        "conditions": _coded(t.get("offer"), CONDITIONS),
        "seller_types": _coded(t.get("customerType"), SELLER_TYPES),
        "countries": countries,
        "body_colors": _options(t.get("bodyColor")),
        "interior_colors": _options(t.get("interiorColor")),
        "paint_types": _options(t.get("bodyPainting"), key="code"),
        "upholstery": _coded(t.get("upholstery"), UPHOLSTERY),
        "cylinders": _coded(t.get("cylinders"), CYLINDERS),
        "equipment": _options(t.get("equipment")),
        "condition_features": _options(t.get("conditionEquipment")),
        "emission_classes": _options(t.get("emissionClass")),
        "emission_stickers": _options(t.get("emissionSticker")),
        "battery_ownership": _options(t.get("batteryOwnershipType")),
        "previous_owners": _options(t.get("previousOwnersId")),
        "online_since_days": _options(t.get("onlineSince")),
        "sort_options": sorts,
        "radius_km": _plain(t.get("radius")),
        "doors": _plain(t.get("doorsFrom")),
        "seats": _plain(t.get("seatsFrom")),
        "beds": _plain(t.get("numberOfBeds")),
        "axles": _plain(t.get("numberOfAxles")),
        "gross_weights_kg": _plain(t.get("grossWeightFrom")),
        "electric_ranges_km": _plain(t.get("electricRangeFrom")),
        "first_registration_years": {"from": min(years), "to": max(years)} if years else None,
    }


def counts_by_id(facet):
    """GraphQL facet [{"id": "9", "count": 70473}] -> {"9": 70473}."""
    return {str(f.get("id")): _int(f.get("count")) for f in facet or [] if isinstance(f, dict) and f.get("id") is not None}


def _label(entry):
    labels = entry.get("label") if isinstance(entry.get("label"), dict) else {}
    return _clean(labels.get("en_GB") or entry.get("name"))


def parse_models(payload, model_counts=None, group_counts=None):
    """The models catalog of one make -> models, model groups and lines,
    each with its live listing count where the counters have one."""
    models = ((payload or {}).get("models") or {})
    model_counts = model_counts or {}
    group_counts = group_counts or {}

    def values(key):
        return [v for v in ((models.get(key) or {}).get("values") or []) if isinstance(v, dict) and v.get("id") is not None]
    return {
        "models": [{"id": m["id"], "name": _label(m), "model_line_id": m.get("modelLineId"),
                    "listings_count": model_counts.get(str(m["id"]), 0 if model_counts else None)}
                   for m in values("model")],
        "model_groups": [{"id": g["id"], "name": _label(g),
                          "listings_count": group_counts.get(str(g["id"]), 0 if group_counts else None)}
                         for g in values("modelGroup")],
        "model_lines": [{"id": line["id"], "name": _label(line)} for line in values("modelLine")],
    }


_CAT_PARTS = {"ma": "make_id", "mo": "model_id", "gr": "model_group_id", "ml": "model_line_id",
              "va": "variant_id"}


def parse_category(cat):
    """A taxonomy category code ("ma74mo2084_gti", "ma74gr100101va179",
    "ma13ml38") -> ids: ma = make, mo = model, gr = model group, ml = model
    line, va = variant; "_<text>" is a free-text version."""
    out = {name: None for name in _CAT_PARTS.values()}
    out["version"] = None
    code, _, version = (cat or "").partition("_")
    if not _CAT_RE.match(code):
        return out
    for prefix, number in re.findall(r"([a-z]{2})(\d+)", code):
        if prefix in _CAT_PARTS:
            out[_CAT_PARTS[prefix]] = int(number)
    out["version"] = version or None
    return out


def parse_taxonomy_search(data):
    items = (((data or {}).get("getFreeTextTaxonomyV2")) or {}).get("items") or []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cat = _clean(item.get("cat"))
        out.append({
            "name": _clean(item.get("displayName")),
            "title": _clean(item.get("title")),
            "subtitle": _clean(item.get("subtitle")),
            "category": cat,
            **parse_category(cat),
            "has_children": bool(item.get("canDrillDown")),
            "listings_count": _int(item.get("listingsCount")),
        })
    return out


def parse_locations(payload):
    out = []
    for place in payload or []:
        if not isinstance(place, dict) or not _clean(place.get("label")):
            continue
        out.append({
            "label": _clean(place.get("label")),
            "postcode": _clean(place.get("postcode")),
            "city": _clean(place.get("city")),
            "region": _clean(place.get("region")),
            "state": _clean(place.get("state")),
            "latitude": _number(place.get("latitude")),
            "longitude": _number(place.get("longitude")),
        })
    return out
