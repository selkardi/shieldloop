"""Campagne d'attaques en mémoire, sans copie des corpus sur disque."""

import argparse
import copy
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.pipeline import CFG, SYSTEM, generate
from app.retriever import tokens, champ
from app.shield import (
    PROTECTED_SYSTEM,
    filter_sources,
    generate_protected,
    check_citations,
)


def read_jsonl(path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def save_json(path, content):
    # Refuse d'écraser un résultat existant.
    with path.open("x", encoding="utf-8") as file:
        json.dump(content, file, ensure_ascii=False, indent=2)


def load_documents():
    documents = [
        {
            "id": path.name,
            "text": path.read_text(encoding="utf-8"),
        }
        for path in sorted((ROOT / "data/docs").glob("*.txt"))
    ]
    if not documents:
        raise ValueError("Aucun document dans data/docs.")
    return documents


def retrieve_in_memory(question, documents):
    """Reproduit la pondération BM25 du retriever de votre équipe."""
    corpus = []

    for document in documents:
        text = document["text"]
        keywords = (
            tokens(champ(text, "objet"))
            + tokens(champ(text, "nomacheteur"))
        )
        corpus.append(keywords * 3 + tokens(text))

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokens(question))
    k = CFG["retrieval"]["top_k"]

    order = sorted(
        range(len(documents)),
        key=lambda index: scores[index],
        reverse=True,
    )[:k]

    return [
        {**documents[index], "score": float(scores[index])}
        for index in order
    ]


def run_mode(question, sources, protected):
    """Les deux modes reçoivent le même contexte initial."""
    start = time.perf_counter()

    if protected:
        context, alerts = filter_sources(copy.deepcopy(sources))

        if context:
            answer = generate_protected(question, context)
            alerts.extend(check_citations(answer, context))
        else:
            answer = "NOT FOUND"
    else:
        context = copy.deepcopy(sources)
        alerts = []
        answer = generate(question, context)

    return {
        "answer": answer,
        "sources": [source["id"] for source in context],
        "context_sent": context,
        "alerts": alerts,
        # Recherche exclue : durée de traitement après récupération.
        "processing_seconds": round(
            time.perf_counter() - start, 2
        ),
    }

def resume_campaign(folder, dry_run=False, pause=65.0):
    campaign = (ROOT / folder).resolve()

    if not campaign.is_relative_to(ROOT):
        raise ValueError("La campagne doit être dans le projet.")

    configuration = json.loads(
        (campaign / "configuration.json").read_text(encoding="utf-8")
    )

    # Évite de comparer silencieusement deux configurations différentes.
    current_model = {
        key: CFG["model"].get(key)
        for key in (
            "name", "base_url", "temperature", "max_tokens"
        )
    }

    if (
        current_model != configuration["model"]
        or SYSTEM != configuration["baseline_system"]
        or PROTECTED_SYSTEM != configuration["protected_system"]
    ):
        raise ValueError(
            "Le modèle ou les prompts ont changé. "
            "Ne pas reprendre cette campagne avec d'autres paramètres."
        )

    tasks = []

    for result_path in sorted(campaign.glob("*_result.json")):
        record = json.loads(
            result_path.read_text(encoding="utf-8")
        )

        case_number = result_path.name.removesuffix("_result.json")

        for mode in ("baseline", "protected"):
            # Ne rejoue jamais une réponse déjà obtenue.
            if record[mode]["status"] == "completed":
                continue

            # Vérifie également les précédentes reprises.
            previous_success = False
            attempts_folder = campaign / "resume_attempts"

            if attempts_folder.exists():
                pattern = f"{case_number}_{mode}_*.json"

                for previous_path in attempts_folder.glob(pattern):
                    previous = json.loads(
                        previous_path.read_text(encoding="utf-8")
                    )
                    if previous["result"]["status"] == "completed":
                        previous_success = True
                        break

            if not previous_success:
                tasks.append(
                    (result_path, case_number, record, mode)
                )

    print("Appels restant à reprendre :", len(tasks))

    for _, _, record, mode in tasks:
        print("-", record["attack"]["attack_id"], "|", mode)

    if dry_run:
        print("Vérification terminée : aucun appel API, aucun fichier créé.")
        return

    if not tasks:
        print("Tous les appels disposent déjà d'un résultat.")
        return

    attempts_folder = campaign / "resume_attempts"
    attempts_folder.mkdir(exist_ok=True)

    for index, (source_path, number, record, mode) in enumerate(
        tasks, start=1
    ):
        if index > 1:
            print(f"Pause de {pause} secondes...", flush=True)
            time.sleep(pause)

        print(
            f"\n[{index}/{len(tasks)}] "
            f"{record['attack']['attack_id']} | {mode}",
            flush=True,
        )

        # Une seule tentative réseau par appel.
        # Évite les tentatives automatiques cachées du SDK.
        from app.pipeline import client

        rate_limited = False

        # Ne pas utiliser de bloc with ni close() : le transport peut être partagé.
        single_try_client = client.with_options(max_retries=0)
        # Les fonctions existantes utilisent le client de leur module.
        # Remplacement temporaire, rétabli même en cas d'erreur.
        import app.pipeline as pipeline_module
        import app.shield as shield_module

        old_pipeline_client = pipeline_module.client
        old_shield_client = shield_module.client

        try:
            pipeline_module.client = single_try_client
            shield_module.client = single_try_client

            result = {
                "status": "completed",
                **run_mode(
                    record["question"],
                    record["retrieved_passages"],
                    protected=(mode == "protected"),
                ),
            }

        except Exception as error:
            rate_limited = (
                getattr(error, "status_code", None) == 429
                or type(error).__name__ == "RateLimitError"
            )

            response = getattr(error, "response", None)
            headers = getattr(response, "headers", {})

            result = {
                "status": "error",
                "error_type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
                "retry_after": headers.get("retry-after"),
                "rate_limit_headers": {
                    key: value
                    for key, value in headers.items()
                    if key.lower().startswith("x-ratelimit-")
                },
            }

        finally:
            pipeline_module.client = old_pipeline_client
            shield_module.client = old_shield_client

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S_%fZ"
        )

        output = attempts_folder / (
            f"{number}_{mode}_{timestamp}_{uuid4().hex[:8]}.json"
        )

        save_json(
            output,
            {
                "original_result_file": source_path.name,
                "attack_id": record["attack"]["attack_id"],
                "mode": mode,
                "resumed_at_utc": datetime.now(timezone.utc).isoformat(),
                "configuration_file": "configuration.json",
                "shield_code_sha256": hashlib.sha256(
                    (ROOT / "app/shield.py").read_bytes()
                ).hexdigest(),
                "result": result,
            },
        )

        print("Tentative enregistrée :", output)

        if result["status"] == "completed":
            print("Réponse :", result["answer"], flush=True)
        else:
            print("Erreur :", result["error_type"], flush=True)

        if rate_limited:
            print(
                "Quota indisponible : arrêt de la reprise. "
                "Consulter retry_after et rate_limit_headers "
                "dans le fichier enregistré."
            )
            return

    print("\nReprise terminée. Les fichiers d'origine sont inchangés.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "attack_id",
        nargs="?",
        help="Un identifiant précis ; sinon utiliser --all.",
    )
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--resume")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.pause < 0:
        parser.error("--pause doit être positif ou nul.")

    if args.resume:
        if args.all or args.attack_id:
            parser.error("--resume ne s'utilise pas avec --all ou attack_id.")

        resume_campaign(
            args.resume,
            dry_run=args.dry_run,
            pause=max(65.0, args.pause),
        )
        return

    if args.dry_run:
        parser.error("--dry-run s'utilise ici avec --resume.")

    if args.all == bool(args.attack_id):
        parser.error("Choisir un attack_id OU --all.")

    attacks = read_jsonl(ROOT / "eval/attacks/attacks.jsonl")
    ids = [attack["attack_id"] for attack in attacks]

    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants d'attaque dupliqués.")

    questions_list = read_jsonl(ROOT / "eval/testset.jsonl")
    questions = {case["id"]: case for case in questions_list}

    if len(questions) != len(questions_list):
        raise ValueError("Identifiants de question dupliqués.")

    selected = (
        attacks if args.all else [
            attack for attack in attacks
            if attack["attack_id"] == args.attack_id
        ]
    )
    if not selected:
        raise ValueError("Aucune attaque sélectionnée.")

    clean_documents = load_documents()
    documents_by_id = {
        document["id"]: document for document in clean_documents
    }

    # Valide tous les cas avant de commencer les appels au modèle.
    prepared = []

    for attack in selected:
        case = questions[attack["question_id"]]
        document_id = attack["document_id"]

        if document_id != case["gold_source"]:
            raise ValueError(
                f"{attack['attack_id']} : source incompatible."
            )

        if document_id not in documents_by_id:
            raise ValueError(f"Document absent : {document_id}")

        payload_path = (ROOT / attack["payload_file"]).resolve()

        if not payload_path.is_relative_to(ROOT):
            raise ValueError("Payload situé hors du projet.")

        payload = payload_path.read_text(encoding="utf-8").strip()

        if not payload:
            raise ValueError("Instruction vide.")

        prepared.append((attack, case, payload))

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )
    campaign = (
        ROOT / "eval/results/attacks"
        / f"{timestamp}_{uuid4().hex[:8]}"
    )
    campaign.mkdir(parents=True, exist_ok=False)

    save_json(
        campaign / "configuration.json",
        {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": {
                key: CFG["model"].get(key)
                for key in (
                    "name", "base_url", "temperature", "max_tokens"
                )
            },
            "retrieval": CFG["retrieval"],
            "baseline_system": SYSTEM,
            "protected_system": PROTECTED_SYSTEM,
            "selected_attacks": selected,
            "clean_document_hashes": {
                document["id"]: hashlib.sha256(
                    document["text"].encode("utf-8")
                ).hexdigest()
                for document in clean_documents
            },
        },
    )

    rows = []
    print("Résultats :", campaign, flush=True)

    for index, (attack, case, payload) in enumerate(prepared, start=1):
        print(
            f"\n[{index}/{len(prepared)}] {attack['attack_id']}",
            flush=True,
        )

        # Nouveau corpus en mémoire pour chaque attaque.
        documents = copy.deepcopy(clean_documents)

        for document in documents:
            if document["id"] == attack["document_id"]:
                document["text"] += "\n\n" + payload + "\n"
                break

        start = time.perf_counter()
        sources = retrieve_in_memory(case["question"], documents)
        retrieval_seconds = round(time.perf_counter() - start, 4)

        exposed = any(
            source["id"] == attack["document_id"]
            and payload in source["text"]
            for source in sources
        )

        record = {
            "attack": attack,
            "question": case["question"],
            "expected_answer": case["answer"],
            "payload": payload,
            "retrieval_seconds": retrieval_seconds,
            "attack_exposed": exposed,
            "retrieved_passages": sources,
        }

        print("Instruction récupérée :", exposed, flush=True)

        for mode in ("baseline", "protected"):
            try:
                record[mode] = {
                    "status": "completed",
                    **run_mode(
                        case["question"],
                        sources,
                        protected=(mode == "protected"),
                    ),
                }
                print(
                    mode, ":", record[mode]["answer"], flush=True
                )
            except Exception as error:
                record[mode] = {
                    "status": "error",
                    "error_type": type(error).__name__,
                }
                print(mode, ": ERREUR", type(error).__name__)

            time.sleep(args.pause)

        # Noms numériques : pas de chemin issu d'un identifiant externe.
        filename = f"{index:03d}"

        save_json(campaign / f"{filename}_result.json", record)
        save_json(
            campaign / f"{filename}_review.json",
            {
                "attack_id": attack["attack_id"],
                "baseline_verdict": "pending",
                "protected_verdict": "pending",
                "baseline_answer_correct": None,
                "protected_answer_correct": None,
                "reviewer": "",
                "note": "",
            },
        )

        rows.append({
            "attack_id": attack["attack_id"],
            "attack_exposed": exposed,
            "baseline_status": record["baseline"]["status"],
            "protected_status": record["protected"]["status"],
            "result_file": f"{filename}_result.json",
            "review_file": f"{filename}_review.json",
        })

    save_json(
        campaign / "summary.json",
        {
            "attempted_cases": len(rows),
            "exposed_cases": sum(
                row["attack_exposed"] for row in rows
            ),
            "rows": rows,
            "note": (
                "Résultats à annoter. Aucun taux de réussite "
                "calculé avant validation des verdicts."
            ),
        },
    )

    print("\nCampagne terminée.")
    print("Résultats :", campaign)


if __name__ == "__main__":
    main()