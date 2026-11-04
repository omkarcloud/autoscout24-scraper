# 🚗 AutoScout24 Scraper

AutoScout24 Scraper is a **free and open-source** scraper that gets you **unlimited** detailed European car data from AutoScout24 for free.

## ✨ What Can I Get?

- 🚗 **Search 2.4M+ vehicles in 8 countries** — cars, motorbikes, vans, caravans & trailers with 40+ filters
- 🔧 **Full listing details** — price & VAT, 80+ specs, equipment, every photo, financing & Carfax link
- 🏪 **Every dealer & their reviews** — address, phones, opening hours, full stock & customer reviews
- 📊 **Live market counts** — listings by make, model, fuel, body type & colour, plus 300+ makes

## 🎥 Example: A Full AutoScout24 Listing

```json
{
  "id": "93544f76-8d55-4d96-b8ca-adafd4fd18e5",
  "title": "Porsche 911",
  "link": "https://www.autoscout24.com/offers/porsche-911-911-coupe-2-0-fia-gt-dt-fzg-ex-w-roehrl-gasoline-white-cat_ma57mo1950-93544f76-8d55-4d96-b8ca-adafd4fd18e5",
  "status": "active",
  "price": { "amount": 249900, "currency": "EUR", "is_vat_deductible": false, "is_negotiable": false },
  "vehicle": {
    "make": "Porsche",
    "model": "911",
    "version": "911 Coupe 2.0 FIA GT Dt.Fzg/Ex W.Röhrl",
    "condition": "used",
    "mileage_km": 93602,
    "first_registration": "1965-03",
    "body": { "body_type": "Coupe", "color": "White", "doors": 2, "seats": 2 },
    "engine": { "power_kw": 114, "power_hp": 155, "transmission": "Manual", "cylinders": 6, "displacement_cc": 1977, "drivetrain": "Rear Wheel Drive" },
    "equipment": { "extras": ["Sport package", "Sport seats", "Sport suspension"] }
  },
  "images": [
    "https://prod.pictures.autoscout24.net/listing-images/93544f76-8d55-4d96-b8ca-adafd4fd18e5_e1df19d8-44da-4e65-be4c-71b8ba3f9432.jpg/1280x960.webp"
  ],
  "image_count": 48,
  "location": { "country_code": "DE", "zip": "86919", "city": "Utting", "latitude": 48.0231, "longitude": 11.08174 },
  "seller": {
    "type": "dealer",
    "name": "Motorlegenden",
    "contact_name": "Michael Schnabl",
    "link": "https://www.autoscout24.com/dealerinfo/motorlegenden",
    "phones": [{ "type": "office", "number": "+49 (0)880 - 6333983700", "e164": "+498806333983700" }],
    "rating": { "count": 4, "average": 5, "recommend_percentage": 100 }
  },
  "history_report": { "provider": "Carfax", "is_free": true },
  "created_at": "2023-10-31T13:27:00Z"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free AutoScout24 Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/autoscout24-scraper
cd autoscout24-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/listings/details?listing=93544f76-8d55-4d96-b8ca-adafd4fd18e5"
```

```json
{
  "id": "93544f76-8d55-4d96-b8ca-adafd4fd18e5",
  "title": "Porsche 911",
  "status": "active",
  "price": { "amount": 249900, "currency": "EUR" },
  "vehicle": {
    "make": "Porsche",
    "model": "911",
    "version": "911 Coupe 2.0 FIA GT Dt.Fzg/Ex W.Röhrl",
    "mileage_km": 93602,
    "first_registration": "1965-03",
    "engine": { "power_hp": 155, "transmission": "Manual", "cylinders": 6, "displacement_cc": 1977 }
  },
  "image_count": 48,
  "location": { "country_code": "DE", "city": "Utting" },
  "seller": {
    "name": "Motorlegenden",
    "rating": { "count": 4, "average": 5, "recommend_percentage": 100 }
  },
  "created_at": "2023-10-31T13:27:00Z"
}
```

All 13 endpoints are now live at `http://localhost:8000`.

Every call comes back as a 502 "blocked"? AutoScout24 refuses some networks, so set `AUTOSCOUT24_PROXY=http://user:pass@host:port` (a European proxy works) before `python run.py`. Most connections need no proxy at all.

## 📚 Endpoints

13 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Listing Details | `/listings/details` | Price, 80+ specs, equipment, every photo, seller and financing |
| Search Listings | `/listings/search` | 2.4M+ vehicles, 40+ filters, up to 200 per page |
| Search by Link | `/listings/by-link` | Any AutoScout24 search link's results as clean JSON |
| Search Makes & Models | `/taxonomy/search` | Free text to make and model IDs with listing counts |
| Location Autocomplete | `/locations/autocomplete` | Cities and postcodes with coordinates for radius searches |
| Similar Listings | `/listings/similar` | Comparable cars: same model, ±2 years, ±20% price |
| Listing Counts | `/listings/count` | Live counts by make, model, fuel, body type and equipment |
| Dealer Details | `/dealers/details` | Address, phones, hours, contact people, rating and stock size |
| Dealer Listings | `/dealers/listings` | A dealer's whole inventory, 20 per page, with filters |
| Dealer Reviews | `/dealers/reviews` | Every customer review with grades and dealer replies |
| Makes | `/taxonomy/makes` | 300+ car makes and 450+ motorbike makes with live counts |
| Models | `/taxonomy/models` | A make's models, groups and lines with live counts |
| Search Filters | `/taxonomy/filters` | Every body type, colour, equipment and fuel value search accepts |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-autoscout24-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-autoscout24-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-autoscout24-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/listings/details",
    params={"listing": "93544f76-8d55-4d96-b8ca-adafd4fd18e5"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about AutoScout24 Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/autoscout24-scraper-github-whatsapp)

[![Ask Us by Email about AutoScout24 Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20AutoScout24%20Scraper%20API&body=I%20need%20help%20using%20the%20AutoScout24%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/autoscout24-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/autoscout24-scraper)
