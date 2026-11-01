import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.shield import answer_protected

with (ROOT / "eval/testset.jsonl").open(encoding="utf-8") as file:
    cases = [json.loads(line) for line in file if line.strip()]

case = next(item for item in cases if item["id"] == "q01")

# Documents originaux : aucune instruction ajoutée.
result = answer_protected(case["question"], folder="data/docs",)

record = {
    "mode": "protected",
    "corpus_type": "clean",
    "question_id": case["id"],
    "question": case["question"],
    "expected_answer": case["answer"],
    "tested_at_utc": datetime.now(timezone.utc).isoformat(),
    **result,
}

# Sauvegarde uniquement le résultat, sans copie du corpus.
output_folder = ROOT / "eval/results/clean"
output_folder.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
output = output_folder / f"q01_protected_{timestamp}.json"

with output.open("x", encoding="utf-8") as file:
    json.dump(record, file, ensure_ascii=False, indent=2)

quarantines = [alert for alert in result["alerts"] if alert.get("action") == "quarantined"]

warnings = [alert for alert in result["alerts"] if alert.get("action") == "output_warning"]

print("Bonne réponse :", case["answer"])
print("Réponse protégée :", result["answer"])
print("Blocs mis en quarantaine :", len(quarantines))
print("Avertissements de sortie :", len(warnings))
print("Durée :", result["seconds"], "s")

for alert in result["alerts"]:
    print("Alerte :", alert)

print("Résultat enregistré :", output)