import re

_STOPWORDS = {
    "fr": {"le", "la", "les", "des", "une", "un", "et", "pour", "dans", "nous", "vous", "est", "sur",
           "avec", "du", "au", "notre", "votre", "de"},
    "en": {"the", "and", "for", "with", "you", "we", "our", "to", "of", "is", "are", "in", "join", "your"},
}
_ARABIC = re.compile(r"[؀-ۿ]")
_LETTER = re.compile(r"[^\W\d_]")


def detect_languages(text: str) -> list[str]:
    """Languages present in `text` (ar/fr/en), most prominent first."""
    scores: dict[str, int] = {}
    letters = _LETTER.findall(text)
    arabic = _ARABIC.findall(text)
    if letters and len(arabic) / len(letters) >= 0.1:
        scores["ar"] = len(arabic)
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    for lang, stops in _STOPWORDS.items():
        hits = sum(1 for w in words if w in stops)
        if hits >= 3:
            scores[lang] = hits
    return sorted(scores, key=scores.get, reverse=True)
