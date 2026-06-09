# Search Accuracy Fixes

## Main problem found
The app sometimes treated weak database matches as reliable answers. Because of that, it did not always run the allowed-site search, and the AI prompt received unrelated database context mixed with web context.

## Changed files
- `retrieval_service.py`
- `ai_service.py`
- `routes/chat_routes.py`
- `web_search_service.py`
- `.env.example`

## Fixes applied
1. Added stronger hybrid retrieval metadata:
   - `keyword_matches`
   - `phrase_matches`
   - `keyword_coverage`
   - `vector_score`
   - `keyword_bonus`

2. Added `is_internal_result_reliable()` so the app does not trust embedding similarity alone.

3. Changed chat routing so allowed-site search runs when the database result is not reliable, not only when the similarity number is low.

4. Changed the AI prompt to avoid mixing unrelated database facts with allowed-site results.

5. Changed web search settings to read from `.env` instead of hardcoded weak values.

6. Increased default web search accuracy settings:
   - `HTTP_TIMEOUT=25`
   - `MAX_CANDIDATE_URLS=25`
   - `MAX_FETCHED_PAGES=10`
   - `WEB_TOTAL_CHAR_LIMIT=50000`
   - `WEB_LINK_DEPTH=3`
   - `WEB_USE_SITEMAP=true`
   - `WEB_MIN_PAGE_SCORE=1`

## Important after deployment
Run this after changing existing database items:

```bash
python sync_ai_documents.py
```

Restart the deployed service after updating environment variables.
