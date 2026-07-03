from store import supabase

res = supabase.table('news_items').select('id, translated_title_am').eq('review_status', 'published').execute()
items = res.data or []

to_reset = []
for item in items:
    title = item.get('translated_title_am') or ""
    if "[" in title and "]" in title:
        to_reset.append(item['id'])

if to_reset:
    print(f"Resetting {len(to_reset)} items: {to_reset}")
    supabase.table('news_items').update({"review_status": "filtered"}).in_('id', to_reset).execute()
else:
    print("No mock-published items found.")
