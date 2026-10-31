import json, os, sys
# Permet d'importer app/retriever.py depuis le dossier eval/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.retriever import search

K = 3
total = ok = 0
for ligne in open("eval/testset_draft.jsonl", encoding="utf-8"):
    q = json.loads(ligne)
    ids = [d["id"] for d in search(q["question"], k=K)]   # les K documents trouvés
    total += 1
    if q["gold_source"] in ids:      # le bon document est-il parmi eux ?
        ok += 1
    else:
        print("RATÉ :", q["id"], q["gold_source"], "->", ids)
print(f"Le bon document est dans le top {K} : {ok}/{total}")