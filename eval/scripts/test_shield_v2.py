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

result = answer_protected(
    case["question"],
    folder="data/docs_attack",
)

record = {
    "tested_at_utc": datetime.now(timezone.utc).isoformat(),
    "question_id": case["id"],
    "question": case["question"],
    "expected_answer": case["answer"],
    "corpus": "data/docs_attack",
    **result,
}

folder = ROOT / "eval/results/shield_v2"
folder.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
output = folder / f"q01_{timestamp}.json"

with output.open("x", encoding="utf-8") as file:
    json.dump(record, file, ensure_ascii=False, indent=2)

print("Version :", result["shield_version"])
print("Réponse :", result["answer"])
print("Sources :", result["sources"])
print("Alertes :", len(result["alerts"]))
print("Preuve enregistrée :", output)