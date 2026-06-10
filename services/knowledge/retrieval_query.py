"""Build the text to embed for knowledge retrieval.

Pure string logic — no IO, no LLM. For an elided follow-up ("còn học phí thì
sao?") the current question alone embeds without its referent, so we prepend the
previous user turn. Standalone (self-contained) questions are returned verbatim
so their retrieval is unchanged.
"""

# Leading words that signal a follow-up referring back to the prior turn.
_LEADING_CUES = {"còn", "thế", "vậy"}
# Multi-word continuation cues that can appear anywhere in the question.
_PHRASE_CUES = ("thì sao", "so với")
# Nouns that mark a self-contained question (names its own school/topic).
_TOPIC_NOUNS = (
    "học phí", "học bổng", "ký túc xá", "chương trình", "ngành",
    "điểm chuẩn", "chỉ tiêu", "phương thức", "xét tuyển", "trường",
)
# An elliptical question is short; long ones usually carry their own context.
_MAX_ELLIPTICAL_WORDS = 8


def _is_elliptical(question: str) -> bool:
    q = question.strip().lower()
    if not q:
        return False
    words = q.split()
    if len(words) > _MAX_ELLIPTICAL_WORDS:
        return False
    if words[0] in _LEADING_CUES or any(p in q for p in _PHRASE_CUES):
        return True
    if not any(noun in q for noun in _TOPIC_NOUNS):
        return True
    return False


def build_retrieval_query(question: str, prev_user: str) -> str:
    """Text to embed for retrieval.

    Prepends the previous user turn only when (a) there is a previous turn and
    (b) the question looks elliptical; otherwise returns the question verbatim so
    standalone retrieval is byte-for-byte unchanged.
    """
    question = question or ""
    prev_user = (prev_user or "").strip()
    if not prev_user:
        return question
    if not _is_elliptical(question):
        return question
    return f"{prev_user}\n{question}"
