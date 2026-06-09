import json
import re

import numpy as np
from openai import OpenAI

from config import EMBEDDING_MODEL, TOP_K, OPENAI_API_KEY
from database import execute_fetchall

client = OpenAI(api_key=OPENAI_API_KEY)

STOP_WORDS = {
    "ما", "ماذا", "من", "في", "على", "عن", "الى", "إلى", "هل", "هي", "هو", "كم", "متى",
    "اين", "أين", "ماهي", "وش", "وين", "و", "او", "أو", "ال", "هذا", "هذه", "ابي", "ابغى", "اريد",
    "the", "is", "are", "a", "an", "of", "in", "on", "for", "to", "and", "what", "where", "when", "how", "which", "who", "give", "show"
}

ARABIC_ENGLISH_HINTS = {
    "جامعة": ["university", "uoh"],
    "جامعه": ["university", "uoh"],
    "حائل": ["hail", "uoh"],
    "كليات": ["colleges", "college"],
    "كلية": ["college", "colleges"],
    "كليه": ["college", "colleges"],
    "قبول": ["admission", "admissions"],
    "تسجيل": ["registration", "registrar"],
    "عمادة": ["deanship", "dean"],
    "عماده": ["deanship", "dean"],
    "مبنى": ["building"],
    "مبني": ["building"],
    "مباني": ["buildings"],
    "تخصص": ["major", "program"],
    "تخصصات": ["majors", "programs"],
    "برامج": ["programs"],
    "تقويم": ["calendar"],
    "التقويم": ["calendar"],
    "اوفيس": ["office", "office365", "microsoft"],
    "أوفيس": ["office", "office365", "microsoft"],
    "دعم": ["support", "helpdesk"],
    "فني": ["technical"],
    "اعضاء": ["faculty", "staff"],
    "أعضاء": ["faculty", "staff"],
    "هيئة": ["faculty", "staff"],
}


def cosine_similarity(a, b):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def normalize_text_for_search(text):
    text = (text or "").lower()
    arabic_map = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    text = text.translate(arabic_map)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"(.)\1+", r"\1", text)
    return text


def query_terms(query):
    normalized = normalize_text_for_search(query)
    tokens = re.findall(r"[\u0600-\u06FFa-zA-Z0-9]{2,}", normalized)
    terms = []
    for token in tokens:
        if token not in STOP_WORDS and token not in terms:
            terms.append(token)
            for hint in ARABIC_ENGLISH_HINTS.get(token, []):
                if hint not in terms:
                    terms.append(hint)

    filtered = [t for t in tokens if t not in STOP_WORDS]
    for size in (3, 2):
        for i in range(0, max(0, len(filtered) - size + 1)):
            phrase = " ".join(filtered[i:i + size])
            if phrase and phrase not in terms:
                terms.insert(0, phrase)
    return terms


def keyword_stats(text, terms):
    searchable = normalize_text_for_search(text)
    if not terms:
        return {
            "keyword_bonus": 0.0,
            "keyword_matches": 0,
            "phrase_matches": 0,
            "keyword_coverage": 0.0,
        }

    matched_single_terms = set()
    phrase_matches = 0
    raw_score = 0.0

    for term in terms:
        if term in searchable:
            if " " in term:
                phrase_matches += 1
                raw_score += 4.0
            else:
                matched_single_terms.add(term)
                raw_score += 1.0

    single_terms = [t for t in terms if " " not in t]
    coverage = len(matched_single_terms) / max(1, len(single_terms))

    # Keep embeddings as the main signal. The bonus only rescues exact names and phrases.
    return {
        "keyword_bonus": min(raw_score * 0.035, 0.30),
        "keyword_matches": len(matched_single_terms),
        "phrase_matches": phrase_matches,
        "keyword_coverage": coverage,
    }


def keyword_score(text, terms):
    return keyword_stats(text, terms)["keyword_bonus"]


def get_query_embedding(text):
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def search_similar_documents(query_embedding, query_text=None, top_k=TOP_K):
    """Hybrid search: vector similarity + exact keyword/phrase evidence.

    The returned metadata is used later to decide whether a database hit is
    reliable enough to answer from, or whether the app should fall back to the
    allowed website search. This avoids mixing unrelated database rows with live
    web results.
    """
    rows = execute_fetchall("SELECT item_id, content, embedding FROM ai_documents")
    terms = query_terms(query_text or "")
    results = []
    for row in rows:
        try:
            doc_embedding = json.loads(row["embedding"])
            vector_score = cosine_similarity(query_embedding, doc_embedding)
            stats = keyword_stats(row["content"], terms)
            combined_score = vector_score + stats["keyword_bonus"]
            results.append({
                "item_id": row.get("item_id"),
                "content": row["content"],
                "score": combined_score,
                "vector_score": vector_score,
                "keyword_bonus": stats["keyword_bonus"],
                "keyword_matches": stats["keyword_matches"],
                "phrase_matches": stats["phrase_matches"],
                "keyword_coverage": stats["keyword_coverage"],
                "source": "database",
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
