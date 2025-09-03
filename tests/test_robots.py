from pipeline.robots import parse_robots_text


def test_parse_and_allow_deny():
    robots_txt = """
    User-agent: *
    Disallow: /private
    Allow: /public
    """.strip()

    rp = parse_robots_text("https://example.com/some/page", robots_txt)

    assert rp.can_fetch("TestBot", "https://example.com/public/page.html") is True
    assert rp.can_fetch("TestBot", "https://example.com/private/data") is False

