"""Canonical knowledge-topic taxonomy — the single source of truth shared by
ingestion (seed validation, ``KnowledgeSource.topic``) and the chat intent
router (query routing / ``IntentResult.topic``).

Do NOT redefine these sets elsewhere. Both sides import from here so a topic can
never mean one thing at ingest time and another at query time.
"""

# Canonical topics. A chunk's ``topic`` column and a seed's ``topic`` field must
# be one of these (or NULL on multi-topic PDFs, which act as wildcards).
KNOWLEDGE_TOPICS = frozenset({
    "tuition",
    "curriculum",
    "scholarship",
    "dormitory",
    "admission_policy",
    "program_overview",
})

# Aliases the intent LLM or users commonly emit, mapped to a canonical topic.
# Career / job-prospect questions are answered from the "Cơ hội việc làm" section
# of each program-overview page (there is no standalone career corpus), so they
# resolve to program_overview rather than a dead topic that retrieves nothing.
TOPIC_SYNONYMS = {
    "admission_method": "admission_policy",
    "admission_methods": "admission_policy",
    "admission": "admission_policy",
    "admissions": "admission_policy",
    "admission_regulation": "admission_policy",
    "quota": "admission_policy",
    "career": "program_overview",
    "career_opportunity": "program_overview",
    "job": "program_overview",
    "employment": "program_overview",
}


def normalize_topic(value):
    """Canonical topic for a raw value.

    Exact canonical topic → itself; known synonym → its canonical topic;
    anything else (including None) → None. Callers treat None as "no topic"
    (the route is kept; only the secondary topic field is dropped).
    """
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in KNOWLEDGE_TOPICS:
        return key
    return TOPIC_SYNONYMS.get(key)


# Canonical school codes — the exact values stored in the ``school`` column of
# the knowledge corpus. Retrieval matches this column with ``=`` (no fuzzing),
# so the intent router MUST canonicalize an LLM/user school name to one of these
# or the lookup silently returns zero chunks (KnowledgeQA "no data").
KNOWLEDGE_SCHOOLS = frozenset({"HUST", "NEU", "VNU-UET", "MOET"})

# Free-form school names the intent LLM / users commonly emit → canonical code.
# Keys are diacritic-folded + lowercased (see normalize_school); add new aliases
# in that folded form. "bach khoa" assumes Hà Nội (HUST) — revisit if HCMUT is
# ever ingested, since the bare phrase then becomes ambiguous.
SCHOOL_SYNONYMS = {
    "dai hoc bach khoa ha noi": "HUST",
    "truong dai hoc bach khoa ha noi": "HUST",
    "bach khoa ha noi": "HUST",
    "bach khoa": "HUST",
    "hanoi university of science and technology": "HUST",
    "dai hoc kinh te quoc dan": "NEU",
    "truong dai hoc kinh te quoc dan": "NEU",
    "kinh te quoc dan": "NEU",
    "national economics university": "NEU",
    "dai hoc cong nghe": "VNU-UET",
    "truong dai hoc cong nghe": "VNU-UET",
    "dai hoc cong nghe vnu": "VNU-UET",
    "vnu uet": "VNU-UET",
    "uet": "VNU-UET",
}


def normalize_school(value):
    """Canonical corpus code for a raw school name.

    Exact canonical code (any case) → itself; known free-form alias → its code;
    anything else → the original raw value (NOT dropped — an unknown school must
    keep flowing so the route is unchanged and retrieval misses gracefully,
    rather than silently becoming a no-school query). None → None.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return raw
    if raw.upper() in KNOWLEDGE_SCHOOLS:
        return raw.upper()
    from services.text_utils import vietnamese_fold
    return SCHOOL_SYNONYMS.get(vietnamese_fold(raw), raw)
