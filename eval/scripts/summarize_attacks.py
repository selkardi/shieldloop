"""Consolide une campagne existante, sans import du RAG ni appel API."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def consolidate(campaign):
    rows = []
    for path in sorted(campaign.glob("*_result.json")):
        original = read(path)
        number = path.name.removesuffix("_result.json")
        attack = original["attack"]
        review_path = campaign / f"{number}_review.json"
        review = read(review_path) if review_path.exists() else {}
        row = {
            "attack_id": attack["attack_id"],
            "question": original["question"],
            "reference": original["expected_answer"],
            "target_declared": attack["target_answer"],
            "payload": original["payload"],
            "attack_exposed": original.get("attack_exposed"),
            "target_check": "A verifier dans le payload archive",
            "review_note": review.get("note", ""),
        }
        for mode in ("baseline", "protected"):
            result = original.get(mode, {})
            evidence = path.name
            resumed = False
            if result.get("status") != "completed":
                # Premiere reprise reussie : pas de selection de la meilleure reponse.
                for attempt in sorted((campaign / "resume_attempts").glob(
                    f"{number}_{mode}_*.json"
                )):
                    saved = read(attempt)
                    if (saved.get("attack_id") == attack["attack_id"]
                            and saved.get("mode") == mode
                            and saved.get("result", {}).get("status") == "completed"):
                        result = saved["result"]
                        evidence = str(attempt.relative_to(campaign))
                        resumed = True
                        break
            row[f"{mode}_status"] = result.get("status", "missing")
            row[f"{mode}_answer"] = result.get("answer", "")
            row[f"{mode}_seconds"] = result.get("processing_seconds", "")
            row[f"{mode}_evidence"] = evidence
            row[f"{mode}_alerts"] = json.dumps(result.get("alerts", []), ensure_ascii=False)
            verdict = review.get(f"{mode}_verdict", "pending")
            # L'annotation d'une erreur initiale ne s'applique pas a une reprise.
            if resumed or verdict == "api_error" or result.get("status") != "completed":
                verdict = "pending" if result.get("status") == "completed" else "api_error"
                correct = ""
            else:
                correct = review.get(f"{mode}_answer_correct")
                correct = "" if correct is None else correct
            row[f"{mode}_verdict"] = verdict
            row[f"{mode}_answer_correct"] = correct
        rows.append(row)
    if not rows:
        raise ValueError("Aucun fichier *_result.json dans cette campagne.")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", help="Dossier de campagne, depuis la racine du projet")
    args = parser.parse_args()
    campaign = Path(args.campaign).resolve()
    if not campaign.is_dir():
        parser.error("Dossier introuvable. Lancer depuis la racine shieldloop.")
    rows = consolidate(campaign)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = campaign / f"comparison_{stamp}.csv"
    with output.open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    complete = sum(all(row[f"{m}_status"] == "completed" for m in ("baseline", "protected")) for row in rows)
    pending = sum(row[f"{m}_verdict"] == "pending" for row in rows for m in ("baseline", "protected"))
    for row in rows:
        print("\n", row["attack_id"], "| Reference :", row["reference"])
        print("Cible declaree :", row["target_declared"])
        print("Baseline :", row["baseline_answer"] or row["baseline_status"])
        print("Protege :", row["protected_answer"] or row["protected_status"])
    print(f"\nComparaisons completes : {complete}/{len(rows)}")
    print("Verdicts a verifier :", pending)
    print("CSV cree :", output)
    print("Verifier cible declaree / payload, en particulier q06 (34 ou 93).")
    print("Aucun appel API. Aucun fichier de preuve modifie.")


if __name__ == "__main__":
    main()
