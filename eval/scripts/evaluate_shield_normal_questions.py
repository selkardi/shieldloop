"""Évalue le bouclier sur les documents propres, sans copier le corpus."""

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.shield import answer_protected


def norm(text):
    """Normalise accents, espaces et variantes courantes de tirets."""
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def reference_match(case, answer):
    """Score textuel indicatif, pas une vérification sémantique."""
    actual = norm(answer)
    expected = norm(case["answer"])

    if expected == "not found":
        return actual == "not found"

    accepted = case.get("accept") or [case["answer"]]
    return any(norm(value) in actual for value in accepted if value.strip())


def save_new(path, content):
    with path.open("x", encoding="utf-8") as file:
        json.dump(content, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--exclude", nargs="*", default=["q10", "q20", "q27"],)
    args = parser.parse_args()

    if args.limit < 0 or args.pause < 0:
        parser.error("--limit et --pause doivent être positifs ou nuls.")

    with (ROOT / "eval/testset.jsonl").open(encoding="utf-8") as file:
        cases = [json.loads(line) for line in file if line.strip()]

    excluded = set(args.exclude)
    cases = [case for case in cases if case["id"] not in excluded]

    # --limit 0 signifie : toutes les questions non exclues.
    if args.limit:
        cases = cases[:args.limit]

    if not cases:
        raise SystemExit("Aucune question sélectionnée.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_folder = ROOT / "eval/results/clean" / timestamp
    output_folder.mkdir(parents=True, exist_ok=False)

    save_new(
        output_folder / "selection.json",
        {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "protected",
            "corpus": "data/docs",
            "excluded_ids": sorted(excluded),
            "selected_cases": cases,
            "scoring": "Correspondance textuelle à vérifier manuellement",
        },
    )

    rows = []

    for position, case in enumerate(cases, start=1):
        print(f"\n[{position}/{len(cases)}] {case['id']}", flush=True)

        try:
            result = answer_protected(case["question"], folder="data/docs",)
        except Exception as error:
            row = {"id": case["id"], "status": "error", "error_type": type(error).__name__,}
            save_new(output_folder / f"{position:03d}.json", row)
            rows.append(row)
            print("ERREUR :", row["error_type"])
        else:
            quarantines = sum(alert.get("action") == "quarantined" for alert in result["alerts"])
            warnings = sum(alert.get("action") == "output_warning" for alert in result["alerts"])

            row = {
                "id": case["id"],
                "status": "completed",
                "question": case["question"],
                "expected_answer": case["answer"],
                "accept": case.get("accept", []),
                "reference_match": reference_match(case, result["answer"]),
                "quarantined_blocks": quarantines,
                "output_warnings": warnings,
                "manual_review": "pending",
                **result,
            }

            save_new(output_folder / f"{position:03d}.json", row)
            rows.append(row)

            print("Réponse :", result["answer"])
            print("Correspondance référence :", row["reference_match"])
            print("Blocs isolés :", quarantines)
            print("Avertissements :", warnings)
            print("Durée :", result["seconds"], "s")

        if position < len(cases):
            time.sleep(args.pause)

    completed = [row for row in rows if row["status"] == "completed"]
    durations = sorted(row["seconds"] for row in completed)

    if durations:
        middle = len(durations) // 2
        median = (durations[middle] if len(durations) % 2 else (durations[middle - 1] + durations[middle]) / 2)
    else:
        median = None

    summary = {
        "attempted": len(rows),
        "completed": len(completed),
        "errors": len(rows) - len(completed),
        "reference_matches": sum(row["reference_match"] for row in completed),
        "cases_with_quarantine": sum(row["quarantined_blocks"] > 0 for row in completed),
        "cases_with_output_warning": sum(row["output_warnings"] > 0 for row in completed),
        "median_seconds": (round(median, 2) if median is not None else None),
        "note": ("Scores textuels provisoires. Les quarantaines sur corpus "
                  "propre sont des fausses alertes potentielles à examiner."),
    }

    save_new(output_folder / "summary.json", summary)

    print("\nRÉSUMÉ")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Résultats :", output_folder)


if __name__ == "__main__":
    main()