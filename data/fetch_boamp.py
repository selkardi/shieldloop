import os, re, json, glob, hashlib, requests

URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
OUT = "data/docs"
CIBLE = 25          # nombre de candidats à garder (tu en retiendras 20 après tri)
MAX_PAGES = 10      # 10 pages x 100 avis = 1000 avis parcourus au maximum
MOTS = ["travaux", "bâtiment", "batiment", "construction", "rénovation", "renovation",
        "maçonnerie", "réhabilitation", "rehabilitation", "aménagement", "voirie", "toiture"]

os.makedirs(OUT, exist_ok=True)
# On efface les anciens fichiers pour ne pas mélanger deux exécutions
for ancien in glob.glob(os.path.join(OUT, "ao_*.txt")):
    os.remove(ancien)

def nettoyer(t):
    # Retire e-mails et téléphones : pas de données personnelles dans le corpus
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email retiré]", t)
    t = re.sub(r"(?:\+33|0)\s?[1-9](?:[\s.]?\d{2}){4}", "[tel retiré]", t)
    return t

def aplatir(x, prefixe=""):
    # Transforme n'importe quelle structure (dict, liste, JSON dans un texte) en lignes "chemin: valeur"
    lignes = []
    if isinstance(x, str):
        s = x.strip()
        if s and s[0] in "{[":
            try:
                return aplatir(json.loads(s), prefixe)
            except Exception:
                pass
        if s:
            lignes.append(f"{prefixe}: {s}")
    elif isinstance(x, dict):
        for k, v in x.items():
            lignes += aplatir(v, f"{prefixe}.{k}" if prefixe else k)
    elif isinstance(x, list):
        for v in x:
            lignes += aplatir(v, prefixe)
    elif x is not None:
        lignes.append(f"{prefixe}: {x}")
    return lignes

def en_texte(rec):
    vues, lignes = set(), []
    for l in aplatir(rec):
        l = l[:600]                       # on coupe les lignes trop longues
        if l not in vues:                 # on retire les lignes en double
            vues.add(l)
            lignes.append(l)
    return "\n".join(lignes)[:5000]       # on limite la taille totale du document

def valide(texte):
    bas = texte.lower()
    return (any(m in bas for m in MOTS)                         # sujet BTP
            and "limite" in bas                                  # parle d'une date limite
            and re.search(r"offre|candidature|r[ée]ponse", bas)  # liée aux offres
            and re.search(r"\b20\d{2}\b", texte)                 # contient une année
            and len(texte) >= 600)                               # assez de contenu

n, vus, scannes = 0, set(), 0
index = []
champs_affiches = False

for page in range(MAX_PAGES):
    r = requests.get(URL, params={"limit": 100, "offset": page * 100}, timeout=30)
    if r.status_code != 200:
        print("Erreur API", r.status_code, r.text[:300])
        break
    records = r.json().get("results", [])
    if not records:
        break
    if not champs_affiches:
        print("Champs disponibles :", list(records[0].keys()))
        champs_affiches = True
    for rec in records:
        scannes += 1
        texte = en_texte(rec)
        empreinte = hashlib.md5(texte[:300].encode("utf-8")).hexdigest()
        if empreinte in vus or not valide(texte):
            continue
        vus.add(empreinte)
        n += 1
        nom = f"ao_{n:02d}.txt"
        entete = "[DOCUMENT RÉEL - source : BOAMP/DILA, Licence Ouverte]\n"
        with open(os.path.join(OUT, nom), "w", encoding="utf-8") as f:
            f.write(entete + nettoyer(texte))
        extrait = nettoyer(texte)[:150].replace("\n", " | ")
        index.append(f"{nom}\t{len(texte)} car.\t{extrait}")
        if n >= CIBLE:
            break
    if n >= CIBLE:
        break

with open("data/docs_index.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(index))

print(f"{scannes} avis parcourus, {n} documents enregistrés dans {OUT}")