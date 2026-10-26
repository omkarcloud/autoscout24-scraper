"""The Accept-Language header each HTTP session sends."""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def accept_language(proxy=None, country=None):
    """English for every session (the scraper reads www.autoscout24.com,
    whose content is English whatever the header says)."""
    return ACCEPT_LANGUAGE
