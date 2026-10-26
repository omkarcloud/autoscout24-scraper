"""No-op response cache. The scraper calls cached_call() around every
upstream fetch; this standalone build simply runs the call. Plug in your own
cache here (Redis, a dict with expiry...) if you need one."""


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    """Run fn(**data). `namespace` and `ttl` say what to cache and for how
    long, if you add a cache."""
    return fn(**data)
