"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (before the paging links);
results are written to output/*.json. The params are validated by the same
schemas the API uses, so readable values like make="Porsche" just work.
"""
import json
import os

from autoscout24 import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(fn, schema, **params):
    return fn(**schema().load(params))


if __name__ == "__main__":
    # a listing id or any AutoScout24 offer link
    save("listing_porsche_911.json", run(api.listing_details, schemas.ListingSchema,
                                         listing="93544f76-8d55-4d96-b8ca-adafd4fd18e5"))

    # 40+ filters across 8 European markets, up to 200 per page
    save("search_porsche_2021.json", run(api.listings_search, schemas.SearchSchema,
                                         make="Porsche", year_from="2021", page_size="20"))

    # a dealer slug, customer id or dealer page link
    save("dealer_besico.json", run(api.dealer_details, schemas.DealerSchema,
                                   dealer="besico-siller-und-buttenhauser-gmbh"))
