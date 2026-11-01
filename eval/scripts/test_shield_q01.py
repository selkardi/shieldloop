import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.shield import answer_protected

# Réutilise le corpus existant : aucune copie supplémentaire.
RUN_FOLDER = (ROOT / "eval/runs/20261031T131958_728061Z_74d301df")

# Relit la question exacte du test baseline.
manifest = json.loads((RUN_FOLDER / "manifest.json").read_text(encoding="utf-8"))
question = manifest["question"]["question"]

result = answer_protected(question, folder=str(RUN_FOLDER / "corpus"),)

record = {
    "mode": "protected",
    "baseline_run_id": manifest["run_id"],
    "attack_id": manifest["attack"]["attack_id"],
    "question": question,
    "expected_answer": manifest["question"]["answer"],
    "tested_at_utc": datetime.now(timezone.utc).isoformat(),
    **result,
}

# Nom unique pour conserver les essais précédents.
timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
output = RUN_FOLDER / f"protected_{timestamp}.json"

with output.open("x", encoding="utf-8") as file:
    json.dump(record, file, ensure_ascii=False, indent=2)

print("Réponse protégée :", result["answer"])
print("Sources :", result["sources"])
print("Nombre d'alertes :", len(result["alerts"]))
print("Durée :", result["seconds"], "s")
print("Résultat enregistré :", output)