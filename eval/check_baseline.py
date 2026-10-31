import json, os, re, sys, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.pipeline import answer


def norm(t):
    # minuscules, sans accents, et tout type d'espace (insécable, fine...) remplacé par un espace normal
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t)


questions = [json.loads(l) for l in open("eval/testset_draft.jsonl", encoding="utf-8")]
limite = int(sys.argv[1]) if len(sys.argv) > 1 else len(questions)   # ex. : python eval/check_baseline.py 3

ok, temps, resultats = 0, [], []
for q in questions[:limite]:
    try:
        r = answer(q["question"])
    except Exception as e:
        print("ERREUR", q["id"], e)
        time.sleep(10)          # pause en cas de limite de débit de Groq
        continue
    bon = any(norm(a) in norm(r["answer"]) for a in q["accept"])   # une des écritures acceptées apparaît-elle ?
    ok += bon
    temps.append(r["seconds"])
    resultats.append({"id": q["id"], "question": q["question"], "attendu": q["answer"],
                      "reponse": r["answer"], "sources": r["sources"], "correct": bool(bon), "seconds": r["seconds"]})
    print(("OK   " if bon else "FAUX ") + q["id"], f"({r['seconds']}s) |", r["answer"][:110].replace("\n", " "))
    time.sleep(1.5)             # petite pause entre les appels (quotas gratuits)

n = len(resultats)
mediane = sorted(temps)[len(temps) // 2] if temps else 0
print(f"Exactitude : {ok}/{n} | temps médian : {mediane} s")
json.dump(resultats, open("eval/baseline_normal.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)