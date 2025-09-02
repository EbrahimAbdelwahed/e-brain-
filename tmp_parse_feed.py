import feedparser, pathlib
p = pathlib.Path('tests/fixtures/rss/feed1.xml')
print('exists', p.exists())
content = p.read_bytes()
feed = feedparser.parse(content)
print('len entries', len(feed.entries))
print([e.get('title') for e in feed.entries])
