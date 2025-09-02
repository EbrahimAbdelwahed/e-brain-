from pipeline.normalize import canonicalize_url


def test_canonicalize_url_strips_tracking_and_slash():
    url = "https://example.com/article?id=123&utm_source=newsletter&utm_medium=email&ref=home#/section"
    can = canonicalize_url(url)
    assert "utm_" not in can
    assert can.endswith("/section") is False
    assert can.endswith("/") is False

