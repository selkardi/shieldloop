"""Contrôle expérimental des dates : références citées, sans réponse de test.

Ne vérifie pas tous les nombres, les relations sémantiques ou la véracité
de la source. Aucun appel API. Préserve la réponse brute dans le résultat.
"""
import re
import unicodedata
from datetime import date

CHECK_VERSION = "1.0-cited-dates"
BLOCKED_ANSWER = (
    "Réponse non affichée : une date ou sa source n’a pas pu être "
    "validée par le contrôle de sortie. Consultez les sources."
)
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
MONTH_PATTERN = "|".join(MONTHS)


def normalize(text):
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_dates(text):
    """Dates complètes seulement : ISO, JJ/MM/AAAA et français avec année."""
    text = normalize(text)
    patterns = [
        (r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", "ymd"),
        (r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)", "dmy"),
        (rf"\b(\d{{1,2}})(?:er)?\s+({MONTH_PATTERN})\s+(\d{{4}})\b", "fr"),
    ]
    dates = set()
    invalid = []
    for pattern, kind in patterns:
        for match in re.finditer(pattern, text):
            a, b, c = match.groups()
            if kind == "ymd":
                year, month, day = int(a), int(b), int(c)
            else:
                year, day = int(c), int(a)
                month = MONTHS[b] if kind == "fr" else int(b)
            try:
                dates.add(date(year, month, day).isoformat())
            except ValueError:
                invalid.append(match.group(0))
    return dates, invalid


def is_deadline_question(question):
    text = normalize(question)
    return any(word in text for word in ("date limite", "echeance", "deadline"))


def evidence_text(text, deadline):
    """Pour une échéance, limiter l'appui aux champs d'échéance BOAMP."""
    if not deadline:
        return text
    accepted_keys = {
        "datelimitereponse",
        "gestion.indexation.date_limite_reponse",
        "donnees.condition_delai.recept_candidat",
        "donnees.condition_delai.recept_offres",
    }
    values = []
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and normalize(key) in accepted_keys:
            values.append(value)
    # Pas de repli sur dateparution ou datefindiffusion.
    return "\n".join(values)


def validate_output(question, raw_answer, sources):
    """Renvoie réponse publique + état du contrôle ; ne corrige aucun fait."""
    result = {
        "raw_answer": raw_answer,
        "answer": raw_answer,
        "output_blocked": False,
        "output_check": {"version": CHECK_VERSION, "status": "not_applicable"},
        "output_alerts": [],
    }
    if normalize(raw_answer) == "not found":
        result["output_check"]["status"] = "not_found"
        return result

    deadline = is_deadline_question(question)
    asserted, invalid = extract_dates(raw_answer)
    if not asserted and not invalid and not deadline:
        return result

    by_id = {source["id"]: source for source in sources}
    citations = re.findall(r"\[([^\[\]\n]+)\]", raw_answer)
    valid_citations = sorted({c.strip() for c in citations if c.strip() in by_id})
    unknown = sorted({c.strip() for c in citations if c.strip() not in by_id})
    supported = set()
    for source_id in valid_citations:
        dates, _ = extract_dates(evidence_text(by_id[source_id]["text"], deadline))
        supported.update(dates)

    reasons = []
    if invalid:
        reasons.append("invalid_calendar_date")
    if not asserted and deadline:
        reasons.append("no_parseable_deadline")
    if not valid_citations:
        reasons.append("no_valid_cited_source_for_date")
    if unknown:
        reasons.append("unknown_cited_source_for_date")
    unsupported = sorted(asserted - supported)
    if unsupported:
        reasons.append("date_not_supported_by_cited_source")

    result["output_check"].update({
        "status": "blocked" if reasons else "passed",
        "scope": "boamp_deadline_fields" if deadline else "date_presence",
        "answer_dates": sorted(asserted),
        "supported_dates": sorted(supported),
        "cited_source_ids": valid_citations,
        "unknown_citations": unknown,
        "unsupported_dates": unsupported,
        "invalid_dates": invalid,
    })
    if reasons:
        result["answer"] = BLOCKED_ANSWER
        result["output_blocked"] = True
        result["output_alerts"] = [{
            "action": "output_blocked", "reason": "date_validation_failed",
            "reasons": reasons, "unsupported_dates": unsupported,
        }]
    return result
