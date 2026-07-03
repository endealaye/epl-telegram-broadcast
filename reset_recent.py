from store import supabase
from datetime import datetime, timedelta, timezone

cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
res = supabase.table('news_items').select('id').eq('review_status', 'published').gte('published_at', cutoff).execute()
items = res.data or []

if items:
    ids = [item['id'] for item in items]
    print(f"Resetting {len(ids)} items published in last 24h: {ids}")
    supabase.table('news_items').update({"review_status": "filtered"}).in_('id', ids).execute()
else:
    print("No recently published items found.")
