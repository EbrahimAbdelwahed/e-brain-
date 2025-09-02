from pipeline.io import init_db, db
from pipeline.ingest import fetch_feeds
from pipeline.extract import extract

init_db()
print('fetching...')
print(fetch_feeds(cfg_path='tests/fixtures/sources-fixture.yml'))
with db() as conn:
    cur = conn.execute('select count(*) as c from raw_articles')
    print('raw count', cur.fetchone()['c'])
print('extracting...')
print(extract(parallel=2))
with db() as conn:
    cur = conn.execute('select count(*) as c from articles')
    print('articles count', cur.fetchone()['c'])
