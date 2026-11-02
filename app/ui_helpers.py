"""Helpers for the Streamlit interface. No Streamlit import here, so they are easy to test.

The interface only needs three things from the rest of the project:
  - app.pipeline.answer(question, folder=...)  -> {"answer", "sources", "seconds"}
  - a protected version with the same signature and the same output format
  - eval/testset.jsonl (fields: id, question, gold_source, answer, accept, tags)
"""
import importlib
import inspect
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "eval" / "ui_cache.json"
TESTSET_PATH = ROOT / "eval" / "testset.jsonl"
# If the shield function has another name, add it here.
PROTECTED_NAMES = ("answer_protected", "protected_answer", "answer_with_shield", "answer_shielded")
CORE_KEYS = {"answer", "sources", "seconds"}
# Extra fields returned by the shield (app/shield.py): shown with dedicated widgets.
SHIELD_KEYS = {"alerts", "retrieved_passages", "filtered_passages"}
ATTACK_RESULTS = ROOT / "eval" / "results" / "attacks"


# ---------- text comparison ----------
def norm(text) -> str:
    """Lowercase, no accents, normalised spaces (also non-breaking ones)."""
    text = str(text).replace(" ", " ").replace(" ", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).lower().strip()


def contains_any(text, values) -> bool:
    """True if one of the values appears in the text (after normalisation)."""
    haystack = norm(text)
    return any(v and norm(v) in haystack for v in values)


# ---------- test set ----------
def load_questions(path: Path = TESTSET_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def accepted_values(q: dict) -> list[str]:
    """Values that make an answer correct: the `accept` list, else the reference answer."""
    vals = q.get("accept") or [q.get("answer")]
    return [v for v in vals if v]


# ---------- calling the assistants ----------
def find_protected_answer():
    """Return (function, None) or (None, error message)."""
    errors = []
    for modname in ("app.shield", "app.pipeline"):
        try:
            module = importlib.import_module(modname)
        except Exception as exc:  # missing file, missing key, import error...
            errors.append(f"{modname} : {type(exc).__name__}: {exc}")
            continue
        for name in PROTECTED_NAMES:
            fn = getattr(module, name, None)
            if callable(fn):
                return fn, None
    hint = " ; ".join(errors) if errors else "aucune des fonctions " + ", ".join(PROTECTED_NAMES)
    return None, f"Assistant protégé introuvable ({hint})."


def call_assistant(fn, question: str, folder: str | None = None) -> dict:
    """Call an assistant function; pass `folder` only if the function accepts it."""
    kwargs = {}
    if folder is not None and "folder" in inspect.signature(fn).parameters:
        kwargs["folder"] = folder
    return fn(question, **kwargs)


# ---------- voice input (speech -> text, via Groq's Whisper) ----------
TRANSCRIBE_MODEL = "whisper-large-v3-turbo"   # if Groq refuses it, try "whisper-large-v3"


def transcribe_audio(data: bytes, filename: str = "question.wav", language: str = "fr") -> str:
    """Turn a recorded question into text. The text then goes through the normal pipeline."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY manquante dans le fichier .env")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    result = client.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=(filename, data), language=language)
    return result.text.strip()


def is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in text or "rate limit" in text or "429" in text


# ---------- cache (so a demo can replay saved results when Groq is rate-limited) ----------
def cache_key(kind: str, folder: str, question: str) -> str:
    return f"{kind}|{folder}|{question}"


def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # the cache is a convenience, never a reason to crash


def run_assistant(kind: str, fn, question: str, folder: str, offline_only: bool = False):
    """Return (result or None, status, message).
    status: "live" (fresh call), "cache" (saved result), "missing", "error"."""
    cache = load_cache()
    key = cache_key(kind, folder, question)
    if offline_only:
        if key in cache:
            return cache[key], "cache", None
        return None, "missing", "Aucun résultat enregistré pour cette question (lancez-la une fois en direct)."
    try:
        result = call_assistant(fn, question, folder)
    except Exception as exc:
        if key in cache:
            return cache[key], "cache", f"Appel impossible ({type(exc).__name__}) : résultat enregistré affiché."
        if is_rate_limit(exc):
            return None, "error", "Limite d'appels Groq atteinte : attendez une minute, puis relancez."
        return None, "error", f"{type(exc).__name__} : {exc}"
    cache[key] = json.loads(json.dumps(result, default=str))
    save_cache(cache)
    return result, "live", None


# ---------- result files ----------
def load_json_table(path: Path):
    """Read a JSON result file. Return (summary of scalar values, list of flat rows) or None."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    summary, rows = {}, []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and not rows:
                rows = v
            elif isinstance(v, (int, float, str, bool)) or v is None:
                summary[k] = v
    scalar = (int, float, str, bool, type(None))
    flat = [{k: (v if isinstance(v, scalar) else json.dumps(v, ensure_ascii=False)) for k, v in r.items()}
            for r in rows if isinstance(r, dict)]
    return summary, flat


# ---------- shield output (alerts and evidence) ----------
def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def alert_text(alert) -> str:
    if isinstance(alert, str):
        return alert
    if isinstance(alert, dict):
        label = next((str(alert[k]) for k in ("type", "kind", "code") if alert.get(k)), "")
        detail = next((str(alert[k]) for k in ("message", "reason", "description", "text") if alert.get(k)), "")
        if label or detail:
            return " : ".join(p for p in (label, detail) if p)
    return json.dumps(alert, ensure_ascii=False, default=str)


def passage_text(passage) -> str:
    if isinstance(passage, str):
        return passage
    if isinstance(passage, dict):
        text = passage.get("text") or passage.get("content") or ""
        pid = passage.get("id") or passage.get("source")
        if text:
            return f"[{pid}] {text}" if pid else text
    return json.dumps(passage, ensure_ascii=False, default=str)


def diff_passages(retrieved, filtered) -> list[tuple[str, str]]:
    """For each passage before filtering: ('kept') if the same text is still there after, else ('removed or changed')."""
    kept = {norm(passage_text(p)) for p in as_list(filtered)}
    return [(passage_text(p), "conservé" if norm(passage_text(p)) in kept else "retiré ou modifié")
            for p in as_list(retrieved)]


# ---------- saved attack results (eval/results/attacks/<run>/) ----------
def latest_attack_run(base: Path = ATTACK_RESULTS):
    """Newest run folder, preferring one that contains the reviewed comparison."""
    if not base.is_dir():
        return None
    runs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name)
    reviewed = [d for d in runs if (d / "comparison_reviewed.md").exists()]
    pool = reviewed or runs
    return pool[-1] if pool else None


def read_semicolon_csv(path: Path) -> list[dict]:
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def count_pending(rows: list[dict]) -> int:
    return sum(1 for r in rows for k, v in r.items()
               if k and "verdict" in k.lower() and str(v).strip().lower() == "pending")
