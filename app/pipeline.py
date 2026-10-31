"""The whole product logic lives here, as small functions: easy to test, easy to turn into agent tools later."""
import os, time, yaml
from dotenv import load_dotenv
from openai import OpenAI

try:
    from app.retriever import search      # quand on lance depuis la racine du projet
except ImportError:
    from retriever import search          # quand on lance depuis le dossier app/

ROOT = os.path.join(os.path.dirname(__file__), "..")
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
load_dotenv(os.path.join(ROOT, ".env"))
key_env = CFG["model"].get("api_key_env", "none")
# Ollama ignores the key; cloud endpoints need the one named in config.yaml
client = OpenAI(base_url=CFG["model"]["base_url"],
                api_key="ollama" if key_env == "none" else os.environ[key_env])
SYSTEM = open(os.path.join(ROOT, CFG["prompt_file"]), encoding="utf-8").read()


def retrieve(question: str, folder: str | None = None) -> list[dict]:
    """Return the top_k most relevant documents as [{"id": ..., "text": ...}] (BM25).
    `folder` lets another module search another corpus (e.g. data/docs_attack)."""
    if not CFG["retrieval"]["enabled"]:
        return []
    dossier = os.path.normpath(os.path.join(ROOT, folder or CFG["retrieval"].get("folder", "data/docs")))
    return search(question, k=CFG["retrieval"]["top_k"], dossier=dossier)


def generate(question: str, sources: list[dict]) -> str:
    ctx = "\n\n".join(f"[{s['id']}] {s['text']}" for s in sources) or "(no sources)"
    r = client.chat.completions.create(
        model=CFG["model"]["name"], temperature=CFG["model"]["temperature"],
        max_tokens=CFG["model"]["max_tokens"],
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": f"<sources>\n{ctx}\n</sources>\n\nQuestion: {question}"}])
    return (r.choices[0].message.content or "").strip()   # "or ''" évite un plantage si la réponse est vide


def answer(question: str, folder: str | None = None) -> dict:
    t0 = time.time()
    sources = retrieve(question, folder)
    text = generate(question, sources)
    return {"answer": text, "sources": [s["id"] for s in sources], "seconds": round(time.time() - t0, 2)}
