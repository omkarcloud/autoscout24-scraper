"""Start the AutoScout24 Scraper API.

    python run.py            # http://localhost:8000
    PORT=9000 python run.py  # another port

Then:  curl "http://localhost:8000/listings/details?listing=93544f76-8d55-4d96-b8ca-adafd4fd18e5"
"""
import bottle
from cheroot import wsgi

import config
import routes  # noqa: F401  (mounts the routes on bottle's default app)

EXAMPLE = "/listings/details?listing=93544f76-8d55-4d96-b8ca-adafd4fd18e5"


def main():
    app = bottle.default_app()
    print(f"AutoScout24 Scraper listening on http://localhost:{config.PORT}/")
    print(f"Try:  curl \"http://localhost:{config.PORT}{EXAMPLE}\"")
    server = wsgi.Server(("0.0.0.0", config.PORT), app, server_name="autoscout24-scraper", numthreads=16)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
