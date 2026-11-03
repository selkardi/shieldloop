# Data

| Source | What | Licence / permission | Personal data? | How prepared |
|---|---|---|---|---|
| BOAMP (Bulletin officiel des annonces des marchés publics), open data published by the DILA on data.gouv.fr | 25 French public procurement notices (calls for tender), one text file per notice in `data/docs/` (`ao_01.txt` to `ao_25.txt`) | Licence Ouverte / Open Licence (data.gouv.fr/datasets/boamp) | Public notices; names are anonymised | Downloaded with `data/fetch_boamp.py`, anonymised with `data/anonymiser.py`, listed in `data/docs_index.txt`. Each notice is used as a whole document (no chunking). |
| Team-made attack documents | Copies of some of the notices above with one instruction inserted, in `data/docs_attack/` | Derived from the BOAMP notices; synthetic attacks written by the team | No additional personal data | Written by the team to test indirect prompt injection; they are not real notices |
| Test questions | Questions with a reference answer and accepted values, in `eval/testset.jsonl` | Written by the team from the notices | No | Built with `data/make_questions.py` from the real notices; answers come from the documents |

Rules: no personal data unless anonymised with consent where needed; company documents only with written permission; never commit confidential files (use .gitignore).