import re

from config import CLOSE_RESULT_MARGIN, CHAT_MODEL, MIN_SIMILARITY_SCORE, TOP_K
from retrieval_service import client

GREETING_PATTERNS = (
    "السلام عليكم", "سلام", "هلا", "مرحبا", "اهلا", "أهلا", "صباح الخير", "مساء الخير",
    "hi", "hello", "hey", "good morning", "good evening"
)

CLARIFICATION_WORDS = (
    "أي", "اي", "حدد", "توضيح", "تقصد", "which", "clarify", "what do you mean"
)


def detect_message_language(text):
    """Return 'ar' or 'en' based on the CURRENT user message only.

    Do not use UI language or previous conversation language, because those can
    make the assistant answer Arabic while the user is currently writing English
    or the opposite.
    """
    text = text or ""
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "ar"


def pick_by_language(text, arabic_text, english_text):
    return arabic_text if detect_message_language(text) == "ar" else english_text


def normalize_basic_text(text):
    text = (text or "").strip().lower()
    text = text.replace("!", " ").replace(".", " ").replace("؟", " ").replace("?", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_greeting_and_question(text):
    """Return (has_greeting, cleaned_question).

    If the user writes only a greeting, cleaned_question is empty.
    If the user writes a greeting plus a real question, the greeting is removed
    before retrieval so it does not weaken database/web search accuracy.
    The check is normalized, so small spelling differences such as repeated
    letters do not force the bot to search the knowledge base for a greeting.
    """
    original = (text or "").strip()
    normalized = normalize_arabic_for_intent(original) if "normalize_arabic_for_intent" in globals() else normalize_basic_text(original)

    for greeting in sorted(GREETING_PATTERNS, key=len, reverse=True):
        normalized_greeting = normalize_arabic_for_intent(greeting) if "normalize_arabic_for_intent" in globals() else normalize_basic_text(greeting)
        if normalized == normalized_greeting:
            return True, ""
        if normalized.startswith(normalized_greeting + " "):
            # Remove approximately the first words of the greeting from the original text.
            words_to_remove = len(normalized_greeting.split())
            original_words = original.split()
            cleaned = " ".join(original_words[words_to_remove:]).strip(" ،,.-؟?!")
            return True, cleaned
    return False, original


def is_greeting(text):
    return classify_message_intent(text) == "greeting"


def greeting_reply(text):
    return pick_by_language(
        text,
        "وعليكم السلام، كيف أقدر أساعدك؟",
        "Hello. How can I help you?",
    )


def normalize_arabic_for_intent(text):
    """Normalize Arabic/English text for lightweight intent detection.

    This is not used as a knowledge source. It only prevents casual messages
    such as greetings, thanks, and capability questions from being sent to
    database/web retrieval.
    """
    text = (text or "").strip().lower()
    arabic_map = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    text = text.translate(arabic_map)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"(.)\1+", r"\1", text)  # سلاااام -> سلاام
    text = re.sub(r"[^\u0600-\u06FFa-zA-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


UNIVERSITY_TOPIC_RE = re.compile(
    r"(قبول|تسجيل|كليه|كلية|مبنى|مبني|مباني|عماده|عمادة|تخصص|تخصصات|تقويم|"
    r"اوفيس|دعم|بوابه|بوابة|بلاك|بورد|خدمات|كليات|جامعه|جامعة|حائل|"
    r"office|college|admission|registration|building|calendar|support|service|uoh)",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(
    r"(ما|ماذا|من|متى|وين|اين|أين|كيف|كم|هل|وش|ايش|اعطني|ابي|اريد|"
    r"where|what|when|how|which|who|give|show)",
    re.IGNORECASE,
)
SOCIAL_INTENT_RE = re.compile(
    r"(سلام|سلم|هلا|مرحبا|اهلا|اهلين|حياك|صباح|مساء|شكرا|شكر|مشكور|تسلم|يعطيك|"
    r"باي|وداع|مع السلامه|كيفك|شلونك|اخبارك|من انت|وش انت|تقدر تسوي|ساعدني|تمام|"
    r"hello|hi|hey|thanks|thank|bye|goodbye|how are you|who are you|what can you do|help)",
    re.IGNORECASE,
)
SOCIAL_EXACT_RE = re.compile(
    r"^(كيفك|شلونك|كيف حالك|من انت|مين انت|وش انت|وش تقدر تسوي|ايش تقدر تسوي|ساعدني|"
    r"how are you|who are you|what can you do|help)$",
    re.IGNORECASE,
)


def classify_message_intent(text):
    """Classify message without storing every greeting sentence.

    This avoids treating greetings as database knowledge. It also avoids an
    extra OpenAI intent-classification call on every message, which would make
    the chat slower. The detector uses roots, normalized spelling, and question
    signals rather than a complete list of all possible greetings.
    """
    normalized = normalize_arabic_for_intent(text)
    if not normalized:
        return "empty"

    has_greeting, cleaned_question = split_greeting_and_question(text)
    if has_greeting and not cleaned_question:
        return "greeting"
    if has_greeting and cleaned_question:
        cleaned_norm = normalize_arabic_for_intent(cleaned_question)
        if UNIVERSITY_TOPIC_RE.search(cleaned_norm) or QUESTION_RE.search(cleaned_norm):
            return "question"
        if len(cleaned_norm.split()) <= 2:
            return "conversation"

    if UNIVERSITY_TOPIC_RE.search(normalized):
        return "question"

    if SOCIAL_EXACT_RE.match(normalized):
        return "conversation"

    if QUESTION_RE.search(normalized):
        return "question"

    if SOCIAL_INTENT_RE.search(normalized):
        return "conversation"

    if len(normalized.split()) <= 2:
        return "conversation"

    return "question"


CONVERSATIONAL_PATTERNS = {
    "thanks": (
        "شكرا", "شكرًا", "يعطيك العافيه", "يعطيك العافية", "تسلم", "مشكور",
        "thank you", "thanks", "thx",
    ),
    "farewell": (
        "مع السلامه", "مع السلامة", "باي", "وداعا", "bye", "goodbye",
    ),
    "how_are_you": (
        "كيفك", "كيف حالك", "شلونك", "وش اخبارك", "عامل ايه", "how are you",
    ),
    "identity": (
        "من انت", "مين انت", "وش انت", "ما هو دورك", "what are you", "who are you",
    ),
    "capability": (
        "وش تقدر تسوي", "ايش تقدر تسوي", "كيف تساعدني", "ساعدني", "help", "what can you do",
    ),
}


def starts_with_near_phrase(text, phrase):
    text_norm = normalize_arabic_for_intent(text)
    phrase_norm = normalize_arabic_for_intent(phrase)
    if text_norm == phrase_norm or text_norm.startswith(phrase_norm + " "):
        return True
    return False


def is_conversational_message(text):
    """Return True for casual chat that should not query retrieval."""
    return classify_message_intent(text) == "conversation"


def conversational_reply(text):
    normalized = normalize_arabic_for_intent(text)
    is_arabic = detect_message_language(text) == "ar"

    if any(normalize_arabic_for_intent(p) in normalized for p in CONVERSATIONAL_PATTERNS["thanks"]):
        return "العفو. اكتب سؤالك عن الجامعة وسأحاول مساعدتك." if is_arabic else "You're welcome. Ask me about the university and I will help."
    if any(normalize_arabic_for_intent(p) in normalized for p in CONVERSATIONAL_PATTERNS["farewell"]):
        return "مع السلامة." if is_arabic else "Goodbye."
    if any(normalize_arabic_for_intent(p) in normalized for p in CONVERSATIONAL_PATTERNS["how_are_you"]):
        return "بخير، كيف أقدر أساعدك؟" if is_arabic else "I'm fine. How can I help?"
    if any(normalize_arabic_for_intent(p) in normalized for p in CONVERSATIONAL_PATTERNS["identity"]):
        return "أنا مساعد لطلاب جامعة حائل، أجيب حسب البيانات المتاحة ومصادر الجامعة المسموحة." if is_arabic else "I am a University of Hail assistant. I answer using the available data and allowed university sources."
    if any(normalize_arabic_for_intent(p) in normalized for p in CONVERSATIONAL_PATTERNS["capability"]):
        return "أقدر أساعدك في الأسئلة المتعلقة بجامعة حائل، مثل الكليات، المباني، الخدمات، والدعم الفني حسب المصادر المتاحة." if is_arabic else "I can help with University of Hail questions such as colleges, buildings, services, and support based on available sources."
    return greeting_reply(text)


def assistant_already_asked_clarification(recent_messages):
    for msg in reversed(recent_messages[-4:]):
        if msg["role"] == "assistant" and any(word in msg["content"].lower() for word in CLARIFICATION_WORDS):
            return True
    return False





def is_internal_result_reliable(result):
    """Return True only when a database hit has enough evidence to answer from.

    Embeddings alone can give a superficially high score for a related but wrong
    row. Requiring either exact term/phrase evidence or a clearly high vector
    score prevents the database from overriding a better allowed-site result.
    """
    if not result:
        return False
    if result.get("score", 0) < MIN_SIMILARITY_SCORE:
        return False
    if result.get("phrase_matches", 0) >= 1:
        return True
    if result.get("keyword_matches", 0) >= 1 and result.get("keyword_coverage", 0) >= 0.25:
        return True
    if result.get("vector_score", 0) >= 0.42 and result.get("keyword_matches", 0) >= 1:
        return True
    return False


def reliable_internal_results(results):
    return [r for r in (results or []) if is_internal_result_reliable(r)]

def _extract_result_title(result):
    """Return a short user-facing name for a retrieved database result."""
    content = result.get("content", "") or ""
    for line in content.splitlines():
        line = line.strip()
        if line.lower().startswith("title:"):
            return line.split(":", 1)[1].strip()
    for line in content.splitlines():
        line = line.strip()
        if line and not line.lower().startswith(("category:", "description:")):
            return line[:80]
    return f"Item {result.get('item_id', '')}".strip()


def get_ambiguous_database_options(results, max_options=5):
    """Detect when several internal results are plausible answers.

    The older logic returned immediately when the top result was strong, so
    close alternatives were ignored. This made the assistant answer as if one
    item was certain even when several faculty/building/person records matched.
    """
    strong = reliable_internal_results(results)
    if len(strong) < 2:
        return []

    top_score = strong[0].get("score", 0)
    ambiguity_margin = max(CLOSE_RESULT_MARGIN, 0.08)
    close_results = [r for r in strong if (top_score - r.get("score", 0)) <= ambiguity_margin]

    # If the query is short, multiple strong hits are usually ambiguous even if
    # the numeric score gap is slightly wider.
    if len(close_results) < 2 and len((strong[0].get("content") or "").split()) > 0:
        close_results = strong[:2] if (top_score - strong[1].get("score", 0)) <= 0.12 else close_results

    if len(close_results) < 2:
        return []

    options = []
    seen = set()
    for result in close_results[:max_options]:
        title = _extract_result_title(result)
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            options.append(title)
    return options


AMBIGUITY_CLARIFICATION_MARKER = "أحتاج تفاصيل أكثر لأن سؤالك يطابق أكثر من نتيجة."
AMBIGUITY_CLARIFICATION_MARKER_EN = "I need more details because your question matches more than one result."


def build_ambiguity_question(options=None, user_message=""):
    """Ask for details without exposing the candidate list immediately.

    Flow intended for ambiguous database matches:
    1. First ambiguous question -> ask for more details.
    2. User follow-up still does not narrow the result -> show the found results.

    The assistant should not loop by repeatedly asking the user to choose from
    options, and it should not force the user to select a number.
    """
    if detect_message_language(user_message) == "en":
        return (
            "I need more details because your question matches more than one result. "
            "Add one detail such as the full name, college, building, department, or intended service."
        )
    return (
        f"{AMBIGUITY_CLARIFICATION_MARKER} "
        "اكتب تفصيلًا إضافيًا مثل الاسم الكامل، الكلية، المبنى، القسم، أو الخدمة المقصودة."
    )


def get_previous_ambiguity_question(recent_messages):
    """Return the user's previous ambiguous question, if the last assistant turn asked for details."""
    if not recent_messages:
        return None

    last_assistant_index = None
    for index in range(len(recent_messages) - 1, -1, -1):
        msg = recent_messages[index]
        if msg.get("role") == "assistant":
            content = msg.get("content", "") or ""
            if AMBIGUITY_CLARIFICATION_MARKER in content or AMBIGUITY_CLARIFICATION_MARKER_EN in content:
                last_assistant_index = index
            break

    if last_assistant_index is None:
        return None

    for index in range(last_assistant_index - 1, -1, -1):
        msg = recent_messages[index]
        if msg.get("role") == "user":
            return msg.get("content", "")

    return None


def _extract_result_summary(result, max_chars=180):
    content = result.get("content", "") or ""
    useful_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("title:"):
            continue
        useful_lines.append(line)
        if len(" - ".join(useful_lines)) >= max_chars:
            break
    summary = " - ".join(useful_lines).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def build_found_results_response(results, user_message="", max_options=5):
    """Show the candidate results after one failed clarification attempt."""
    language = detect_message_language(user_message)
    strong = reliable_internal_results(results)
    if not strong:
        strong = (results or [])[:max_options]

    lines = [
        "لم تكفِ التفاصيل لتحديد نتيجة واحدة، وهذه أقرب النتائج التي وجدتها:"
        if language == "ar"
        else "The details were not enough to identify one exact result. These are the closest results I found:"
    ]
    seen = set()
    number = 1
    for result in strong[:max_options]:
        title = _extract_result_title(result)
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        summary = _extract_result_summary(result)
        if summary:
            lines.append(f"{number}. {title}: {summary}")
        else:
            lines.append(f"{number}. {title}")
        number += 1

    if number == 1:
        return (
            "لم أجد نتيجة واضحة في البيانات المتاحة. اكتب تفاصيل أكثر عن الشخص، الكلية، المبنى، أو الخدمة."
            if language == "ar"
            else "I did not find a clear result in the available data. Add more details about the person, college, building, or service."
        )

    return "\n".join(lines)


# Backward-compatible stub in case older imports still reference this name.
def parse_ambiguity_selection(user_message, recent_messages):
    return None, None


def needs_basic_clarification(user_message, results, recent_messages, web_results=None):
    web_results = web_results or []
    text = user_message.strip()
    language = detect_message_language(user_message)
    if assistant_already_asked_clarification(recent_messages):
        return False, ""

    # Check ambiguity before accepting the top result. A strong first result
    # does not mean the answer is safe if other results are almost as strong.
    ambiguous_options = get_ambiguous_database_options(results)
    if ambiguous_options:
        return True, build_ambiguity_question(ambiguous_options, user_message)

    if web_results:
        return False, ""

    if results and is_internal_result_reliable(results[0]):
        return False, ""

    if len(text.split()) <= 2 and not any(char.isdigit() for char in text):
        return True, (
            "سؤالك قصير. اكتب تفاصيل أكثر مثل اسم الشخص، المبنى، الكلية، أو الخدمة التي تقصدها."
            if language == "ar"
            else "Your question is too short. Add more details such as the person's name, building, college, or intended service."
        )

    if not results or not is_internal_result_reliable(results[0]):
        return True, (
            "أحتاج تفاصيل أكثر حتى أجاوب بدقة. اذكر اسم الشخص، المبنى، الكلية، أو الموضوع الذي تقصده."
            if language == "ar"
            else "I need more details to answer accurately. Mention the person, building, college, or topic you mean."
        )

    return False, ""


def build_ai_reply(user_message, results, recent_messages, web_results=None, search_query=None):
    strong_results = reliable_internal_results(results)
    context_text = "\n\n---\n\n".join([r["content"] for r in strong_results[:TOP_K]]) if strong_results else ""

    web_text = ""
    if web_results:
        web_blocks = []
        for r in web_results:
            web_blocks.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('link', '')}\n"
                f"Relevant page content:\n{r.get('content', '')}"
            )
        web_text = "\n\n---\n\n".join(web_blocks)

    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_messages[-6:]])
    search_query = search_query or user_message
    response_language = "Arabic" if detect_message_language(user_message) == "ar" else "English"

    prompt = f"""
You are a university assistant for University of Hail students.
Answer ONLY from the provided context. Do not use general memory to add facts.
Use internal database context only when it directly answers the cleaned retrieval query.
Use allowed-site page content when the internal database context is missing, weak, unrelated, or insufficient.
Never merge unrelated internal database facts with allowed-site page content.

Current user message language: {response_language}
Recent conversation is for context only. Do not copy its language unless it matches the current user message.

Recent conversation:
{history_text}

Internal database context:
{context_text}

Allowed-site page content:
{web_text}

Original user message:
{user_message}

Cleaned retrieval query:
{search_query}

Rules:
- Respond in {response_language}. This rule is mandatory even if the context or previous messages are in another language.
- Be concise and direct.
- Do not invent information or complete missing lists from memory.
- If the original message contains a greeting and a question, do not answer only the greeting; answer the question.
- Use the cleaned retrieval query to judge relevance. Ignore any context block that does not directly match it.
- If both database and allowed-site content are present but conflict, prefer the source that directly matches the cleaned query.
- If the answer comes from allowed-site content, mention briefly that it is from the allowed university website/source.
- If the context is related but incomplete, say what was found and what is still missing.
- If no answer is found in the provided context, say that you did not find the information in the available sources.
"""

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": f"You answer only from supplied context and avoid guessing. You MUST answer in {response_language}.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()
