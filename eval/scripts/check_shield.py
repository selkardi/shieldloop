import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.pipeline import retrieve
from app.shield import filter_sources

# Réutilisation du corpus déjà testé, sans copie.
FOLDER = ("eval/runs/20261031T131958_728061Z_74d301df/corpus")

with (ROOT / "eval/testset.jsonl").open(encoding="utf-8") as file:
    cases = [json.loads(line) for line in file if line.strip()]

case = next(item for item in cases if item["id"] == "q01")

sources = retrieve(case["question"], folder=FOLDER)
filtered, alerts = filter_sources(sources)

print("Documents récupérés :", [s["id"] for s in sources])
print("Nombre de blocs isolés :", len(alerts))

for alert in alerts:
    print("\nSource :", alert["source_id"])
    print("Raisons :", alert["reasons"])
    print("Bloc isolé :")
    print(alert["text"])

print("\nTexte conservé pour ao_01.txt :")
for source in filtered:
    if source["id"] == "ao_01.txt":
        print(source["text"])