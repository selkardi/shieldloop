import glob, json, os, re
from collections import Counter
from datetime import datetime

DOSSIER = "data/docs"
SORTIE = "eval/testset_draft.jsonl"
N_EXTRA = 10                 # questions supplémentaires (en plus d'une question "date limite" par document)
IGNORER = ["rectificatif"]   # avis à ne pas utiliser (la date limite a pu être modifiée)
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

def champ(t, cle):
    # Renvoie la valeur de la ligne "cle: valeur" (au début d'une ligne), sinon None
    m = re.search(rf"^{re.escape(cle)}: (.*)$", t, re.M)
    return m.group(1).strip() if m else None

def court(objet, n=110):
    return objet if len(objet) <= n else objet[:n].rsplit(" ", 1)[0] + "…"

def date_fr(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return ("1er" if d.day == 1 else str(d.day)) + f" {MOIS[d.month - 1]} {d.year}"

def formes_date(iso):
    # Écritures acceptées pour la même date
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    f = [date_fr(iso), f"{d.day:02d}/{d.month:02d}/{d.year}", d.strftime("%Y-%m-%d"),
         f"{d.day:02d}-{d.month:02d}-{d.year}"]
    if d.day == 1:
        f.append(f"1 {MOIS[d.month - 1]} {d.year}")
    return list(dict.fromkeys(f))

def questions_extra(t, ident, objet):
    # Questions supplémentaires, créées seulement si l'information existe dans le document
    e = {}
    v = champ(t, "type_marche_facette")
    if v:
        e["type_marche"] = (f"Le marché {ident} est-il un marché de travaux, de services ou de fournitures ?",
                            v.capitalize(), [v.lower()], v)
    v = champ(t, "procedure_libelle")
    if v:
        e["procedure"] = (f"Quelle procédure de passation est utilisée pour le marché {ident} ?",
                          v, [v.lower()], v)
    v = champ(t, "code_departement_prestation")
    if v and re.fullmatch(r"\d{2,3}|2[AB]", v):
        e["departement"] = (f"Quel est le code du département d'exécution du marché {ident} ?", v, [v], v)
    v = champ(t, "donnees.OBJET.ACCORD_CADRE.DUREE_MOIS")
    if v and v.isdigit():
        e["duree"] = (f"Quelle est la durée, en mois, de l'accord-cadre du marché {ident} ?",
                      f"{v} mois", [f"{v} mois"], v)
    v = champ(t, "nomacheteur")
    if v:
        e["acheteur"] = (f"Quel organisme a lancé le marché « {court(objet)} » ?", v, [v.lower()], v)
    return e

# 1) Lecture des documents
docs, compte = [], Counter()
for p in sorted(glob.glob(os.path.join(DOSSIER, "ao_*.txt"))):
    t = open(p, encoding="utf-8").read()
    nom = os.path.basename(p)
    objet, acheteur = champ(t, "objet"), champ(t, "nomacheteur")
    iso_utc = champ(t, "datelimitereponse")
    iso_loc = champ(t, "gestion.INDEXATION.DATE_LIMITE_REPONSE")
    iso = iso_loc or iso_utc
    if not (objet and acheteur and iso):
        print("IGNORÉ (champ manquant) :", nom)
        continue
    if any(m in objet.lower() for m in IGNORER):
        print("IGNORÉ (mot exclu) :", nom)
        continue
    cle = (court(objet).lower(), acheteur.lower())
    compte[cle] += 1
    docs.append({"nom": nom, "t": t, "objet": objet, "acheteur": acheteur, "iso": iso,
                 "decalage": bool(iso_loc and iso_utc and iso_loc[:10] != iso_utc[:10]), "cle": cle})

# 2) Construction des questions
ordre = ["type_marche", "procedure", "departement", "duree", "acheteur"]
questions, nb_extra = [], 0
for i, d in enumerate(docs):
    if compte[d["cle"]] > 1:
        print("IGNORÉ (marché ambigu, doublon objet+acheteur) :", d["nom"])
        continue
    ident = f"« {court(d['objet'])} » lancé par {d['acheteur']}"
    tags = ["normal", "date_limite"] + (["a_verifier"] if d["decalage"] else [])
    questions.append({"question": f"Quelle est la date limite de réponse pour le marché {ident} ?",
                      "gold_source": d["nom"], "answer": date_fr(d["iso"]), "accept": formes_date(d["iso"]),
                      "tags": tags, "_verif": d["iso"][:10], "_t": d["t"]})
    if nb_extra < N_EXTRA:
        dispo = questions_extra(d["t"], ident, d["objet"])
        for j in range(len(ordre)):             # on fait tourner les types pour varier
            typ = ordre[(i + j) % len(ordre)]
            if typ in dispo:
                q, rep, accept, verif = dispo[typ]
                questions.append({"question": q, "gold_source": d["nom"], "answer": rep, "accept": accept,
                                  "tags": ["normal", typ], "_verif": verif, "_t": d["t"]})
                nb_extra += 1
                break

# 3) Vérification : chaque réponse doit se retrouver dans son document
erreurs = 0
for q in questions:
    if q["_verif"] not in q["_t"]:
        print("VÉRIFICATION ÉCHOUÉE :", q["gold_source"], q["question"][:60])
        erreurs += 1

# 4) Écriture
os.makedirs("eval", exist_ok=True)
with open(SORTIE, "w", encoding="utf-8") as f:
    for n, q in enumerate(questions, 1):
        ligne = {"id": f"q{n:02d}", "question": q["question"], "gold_source": q["gold_source"],
                 "answer": q["answer"], "accept": q["accept"], "tags": q["tags"]}
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")

types = Counter(q["tags"][1] for q in questions)
print(f"{len(questions)} questions écrites dans {SORTIE} ({erreurs} erreur(s) de vérification)")
print("Répartition :", dict(types))