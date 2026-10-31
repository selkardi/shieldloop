import glob, os, re, unicodedata
from functools import lru_cache
from rank_bm25 import BM25Okapi

# Mots courants sans intérêt pour la recherche
STOP = {"les", "des", "pour", "par", "sur", "dans", "est", "que", "qui", "quel", "quelle",
        "quels", "quelles", "cette", "ces", "ses", "son", "lance", "avec", "aux", "une"}

def normaliser(t):
    # minuscules + suppression des accents (réhabilitation = rehabilitation)
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def tokens(t):
    # découpe en mots de plus de 2 lettres, sans les mots courants
    return [w for w in re.findall(r"[a-z0-9]+", normaliser(t)) if len(w) > 2 and w not in STOP]

def champ(texte, cle):
    m = re.search(rf"^{re.escape(cle)}: (.*)$", texte, re.M)
    return m.group(1) if m else ""

@lru_cache(maxsize=4)
def _index(dossier):
    # Construit l'index une seule fois par dossier, puis le garde en mémoire
    docs = []
    for p in sorted(glob.glob(os.path.join(dossier, "*.txt"))):
        with open(p, encoding="utf-8") as f:
            docs.append({"id": os.path.basename(p), "text": f.read()})
    corpus = []
    for d in docs:
        cle = tokens(champ(d["text"], "objet")) + tokens(champ(d["text"], "nomacheteur"))
        corpus.append(cle * 3 + tokens(d["text"]))   # objet et acheteur comptent triple
    return docs, BM25Okapi(corpus)

def search(question, k=3, dossier="data/docs"):
    # Renvoie les k documents les mieux notés pour la question
    docs, bm25 = _index(dossier)
    scores = bm25.get_scores(tokens(question))
    ordre = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:k]
    return [{**docs[i], "score": float(scores[i])} for i in ordre]