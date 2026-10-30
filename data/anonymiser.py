import glob, re

# Numéros français sous toutes leurs écritures (espaces, points, tirets, +33, (0))
TEL = re.compile(r"(?:(?:\+|00)\s?33\s?(?:\(0\))?|0)\s?[1-9](?:[\s.\-/]?\d{2}){4}")
MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Champs dont on efface la valeur entière
CHAMPS_CONTACT = {"tel", "telephone", "fax", "mel", "mail", "email", "courriel", "correspondant", "contact"}
# Champs à relire à la main (peuvent contenir un nom de personne)
A_RELIRE = ("contact", "correspondant", "personne")

total = 0
for p in sorted(glob.glob("data/docs/ao_*.txt")):
    original = open(p, encoding="utf-8").read()
    sortie = []
    for ligne in original.split("\n"):
        cle, sep, val = ligne.partition(":")
        dernier = cle.split(".")[-1].strip().lower()
        if sep and (dernier in CHAMPS_CONTACT or dernier.startswith(("tel", "fax"))):
            ligne = f"{cle}: [retiré]"          # on efface toute la valeur du champ
        ligne = TEL.sub("[tel retiré]", ligne)   # puis on cherche les numéros restants
        ligne = MAIL.sub("[email retiré]", ligne)
        if sep and any(a in cle.lower() for a in A_RELIRE) and "[retiré]" not in ligne:
            print("À RELIRE :", p.split("\\")[-1].split("/")[-1], "|", ligne[:120])
        sortie.append(ligne)
    nouveau = "\n".join(sortie)
    if nouveau != original:
        total += 1
        open(p, "w", encoding="utf-8").write(nouveau)
print(total, "fichiers modifiés")
