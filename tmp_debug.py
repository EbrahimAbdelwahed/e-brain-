import os
from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize

os.environ['EMBED_OFFLINE']='1'
os.environ['SUMMARIZE_USE_LLM']='1'
os.environ['OPENROUTER_API_KEY']='test'
os.environ['LLM_OFFLINE']='1'

# reset db
if DB_PATH.exists():
    DB_PATH.unlink()
init_db()

# create articles
with db() as conn:
    upsert_article(conn, Article('a1','https://x/a1','Title A',None,'2025-09-01T00:00:00Z','src',0,'Text A','en',None,0.9,'h1'))
    upsert_article(conn, Article('a2','https://x/a2','Title B',None,'2025-09-01T01:00:00Z','src',0,'Text B','en',None,0.9,'h2'))

# cluster
cs = do_cluster()
print('clusters:', cs)

# summarize twice
summarize()
with db() as conn:
    cur=conn.execute("select cluster_id, version_hash from summaries")
    rows=cur.fetchall()
print('after first:', rows)

summarize()
with db() as conn:
    cur=conn.execute("select cluster_id, version_hash from summaries")
    rows2=cur.fetchall()
print('after second:', rows2)
