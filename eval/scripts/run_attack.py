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
from app.output_checks import validate_output
import importlib

SHIELD_NAME = "original"
SHIELD_PATH = ROOT / "app/shield.py"
shield_module = None


def select_shield(name):
    global SHIELD_NAME, SHIELD_PATH, shield_module
    global PROTECTED_SYSTEM, filter_sources, generate_protected, check_citations, validate_output
    SHIELD_NAME = name
    module_name = "app.shield_candidate" if name == "candidate" else "app.shield"
    SHIELD_PATH = ROOT / ("app/shield_candidate.py" if name == "candidate" else "app/shield.py")
    shield_module = importlib.import_module(module_name)
    PROTECTED_SYSTEM = shield_module.PROTECTED_SYSTEM
    filter_sources = shield_module.filter_sources
    generate_protected = shield_module.generate_protected
    check_citations = shield_module.check_citations
    if name == "candidate":
        validate_output = shield_module.validate_output
    else:
        from app.output_checks import validate_output as original_check
        validate_output = original_check



def read_jsonl(path):
    with path.open(encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def save_json(path, content):
    # Refuse d'écraser un résultat existant.
    with path.open("x", encoding="utf-8") as file:
        json.dump(content, file, ensure_ascii=False, indent=2)


def apply_payload(text, payload, placement=None):
    """Construit la variante en mémoire selon le placement du catalogue."""
    placement = placement or {"kind": "append", "separator": "\n\n"}
    kind = placement.get("kind", "append")

    if kind == "append":
        base = text.rstrip("\r\n") if placement.get("strip_trailing_newlines") else text
        separator = placement.get("separator", "\n\n")
        if separator not in ("\n", "\n\n", "\r\n", "\r\n\r\n"):
            raise ValueError("Séparateur d'ajout non pris en charge.")
        return base + separator + payload + "\n"

    if kind == "append_to_field_value":
        field = placement.get("field", "")
        if not field or any(char in field for char in "\r\n:"):
            raise ValueError("Champ d'injection invalide.")
        lines = text.splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines) if line.startswith(field + ":")]
        if len(matches) != 1:
            raise ValueError(f"Champ {field!r} : une seule occurrence attendue.")
        index = matches[0]
        old = lines[index]
        ending = "\r\n" if old.endswith("\r\n") else ("\n" if old.endswith("\n") else "")
        separator = placement.get("separator", " ")
        if separator != " " or "\n" in payload or "\r" in payload:
            raise ValueError("L'injection dans un champ doit tenir sur une ligne.")
        lines[index] = old.rstrip("\r\n") + separator + payload + ending
        return "".join(lines)

    raise ValueError(f"Placement inconnu : {kind}")


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

    checked = (
        validate_output(question, answer, context)
        if protected else {
            "answer": answer, "raw_answer": answer,
            "output_blocked": False,
            "output_check": {"status": "disabled_for_baseline"},
            "output_alerts": [],
        }
    )
    alerts.extend(checked["output_alerts"])

    return {
        **checked,
        "shield_version": getattr(shield_module, "SHIELD_VERSION", None) if protected else None,
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

    select_shield(configuration.get("shield_name", "original"))

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

    saved_hash = configuration.get("shield_code_sha256")
    current_hash = hashlib.sha256(SHIELD_PATH.read_bytes()).hexdigest()
    if saved_hash is not None and saved_hash != current_hash:
        raise ValueError("Le code du bouclier a changé : créer une nouvelle campagne.")

    saved_check_hash = configuration.get("output_checks_sha256")
    current_check_hash = hashlib.sha256((ROOT / "app/output_checks.py").read_bytes()).hexdigest()
    if saved_check_hash is None or saved_check_hash != current_check_hash:
        raise ValueError("Contrôle de sortie ajouté ou modifié : créer une nouvelle campagne.")

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
                    SHIELD_PATH.read_bytes()
                ).hexdigest(),
                "result": result,
            },
        )

        print("Tentative enregistrée :", output)

        if result["status"] == "completed":
            print("Réponse :", result["answer"], flush=True)
        else:
            print("Erreur :", result["error_type"], flush=True)
            if result.get("retry_after"):
                print("retry_after (secondes) :", result["retry_after"], flush=True)
                try:
                    from datetime import timedelta
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=float(result["retry_after"]))
                    print("Nouvel essai pas avant (UTC) :", retry_at.isoformat(), flush=True)
                except (ValueError, TypeError, OverflowError):
                    pass

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
    parser.add_argument("--catalog", default="eval/attacks/attacks.jsonl")
    parser.add_argument("--questions", default="eval/testset.jsonl")
    parser.add_argument("--shield", choices=("original", "candidate"), default=None)
    parser.add_argument("--pause", type=float, default=65.0)
    parser.add_argument("--resume")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.pause < 0:
        parser.error("--pause doit être positif ou nul.")

    if args.resume:
        if args.all or args.attack_id or args.shield is not None:
            parser.error("--resume utilise le bouclier enregistré ; ne pas ajouter --all, attack_id ou --shield.")

        resume_campaign(
            args.resume,
            dry_run=args.dry_run,
            pause=max(65.0, args.pause),
        )
        return

    select_shield(args.shield or "original")

    if args.all == bool(args.attack_id):
        parser.error("Choisir un attack_id OU --all.")

    catalog = (ROOT / args.catalog).resolve()
    if not catalog.is_relative_to(ROOT):
        raise ValueError("Le catalogue doit rester dans le projet.")
    attacks = read_jsonl(catalog)
    ids = [attack["attack_id"] for attack in attacks]

    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants d'attaque dupliqués.")

    questions_path = (ROOT / args.questions).resolve()
    if not questions_path.is_relative_to(ROOT):
        raise ValueError("Le fichier de questions doit rester dans le projet.")
    questions_list = read_jsonl(questions_path)
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

        # Valide aussi le placement avant tout appel API.
        apply_payload(
            documents_by_id[document_id]["text"],
            payload,
            attack.get("placement"),
        )
        prepared.append((attack, case, payload))

    print("Bouclier :", SHIELD_NAME, getattr(shield_module, "SHIELD_VERSION", ""), flush=True)
    print("Questions :", questions_path.relative_to(ROOT), flush=True)
    print("Catalogue :", catalog.relative_to(ROOT), flush=True)
    print("Cas sélectionnés :", len(prepared), flush=True)
    if args.dry_run:
        for attack, case, payload in prepared:
            placement = attack.get("placement", {"kind": "append", "separator": "\n\n"})
            print(
                attack["attack_id"], "|", case["id"],
                "|", attack["document_id"],
                "|", attack.get("attack_objective", "false_fact"),
                "| placement :", repr(placement),
            )
        print("Instructions et placements validés. Aucun appel API, aucun fichier créé.")
        print("Le dry-run ne teste pas le filtre. Garder les attaques réservées pour la version finale figée.")
        return

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
            "shield_name": SHIELD_NAME,
            "shield_version": getattr(shield_module, "SHIELD_VERSION", None),
            "questions_file": str(questions_path.relative_to(ROOT)),
            "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "catalog": str(catalog.relative_to(ROOT)),
            "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            "output_checks_sha256": hashlib.sha256((ROOT / "app/output_checks.py").read_bytes()).hexdigest(),
            "shield_code_sha256": hashlib.sha256(SHIELD_PATH.read_bytes()).hexdigest(),
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
                document["text"] = apply_payload(
                    document["text"], payload, attack.get("placement")
                )
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

        # Préparer tous les cas avant le premier appel réseau.
        # Chaque appel réel sera journalisé séparément par resume_campaign().
        record["baseline"] = {"status": "pending"}
        record["protected"] = {"status": "pending"}

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
            "prepared_cases": len(rows),
            "exposed_cases": sum(
                row["attack_exposed"] for row in rows
            ),
            "rows": rows,
            "note": (
                "Plan préparé avant appels API. Lire resume_attempts pour les sorties effectives. Aucun taux de réussite "
                "calculé avant validation des verdicts."
            ),
        },
    )

    print("\nTous les cas sont sauvegardés. Début des appels.", flush=True)
    resume_campaign(str(campaign), pause=max(65.0, args.pause))
    print("Résultats :", campaign)


if __name__ == "__main__":
    main()