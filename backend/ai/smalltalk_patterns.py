import re

MAX_SMALLTALK_CHARS = 60

# Greetings, social continuations, and acknowledgements that carry no agent intent.
# Normalized before matching: lowercased, internal whitespace collapsed, leading/trailing
# punctuation stripped — so "how are you ?" and "HI HI" both match.
SMALLTALK_SET: frozenset[str] = frozenset({
    # greetings
    "hi", "hello", "hey", "yo", "sup", "hiya",
    "hi hi", "hey hey",
    "good morning", "good afternoon", "good evening", "good day",
    # social questions
    "how are you", "how are you doing",
    # acknowledgements / reactions
    "thanks", "thank you", "thx", "ty",
    "ok", "okay", "alright", "cool", "got it", "great", "nice",
    "sounds good", "perfect",
    # closings
    "bye", "goodbye", "see you", "cheers",
})

_PUNCT_STRIP_RE = re.compile(r'^[!.,?;:]+|[!.,?;:]+$')
_WHITESPACE_RE = re.compile(r'\s+')


def normalize_for_smalltalk(content: str) -> str:
    s = content.lower().strip()
    s = _WHITESPACE_RE.sub(' ', s)
    s = _PUNCT_STRIP_RE.sub('', s).strip()
    return s
