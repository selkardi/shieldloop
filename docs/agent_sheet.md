# Agent sheet · ShieldLoop (Session 1)

## Sheet

| Field | Value |
|---|---|
| **Gen AI product** | RAG assistant over BOAMP public tender notices (BM25 + gpt-oss-20b on Groq), protected against indirect prompt injection |
| **Goal** | Answer purchasing questions using cited BOAMP notices, investigate suspicious content, and temporarily quarantine notices pending human review |
| **Read tools** | `search_notices`, `get_notice`, `verify_values`, `list_deadlines`, `list_quarantined_notices` |
| **Write tools (side effects)** | `quarantine_notice`: temporarily exclude a suspicious notice from retrieval and save the evidence · `save_incident_report`: record findings for human review |
| **How we check success** | Answers are correct and cited; suspicious notices are excluded and logged; deadline lists use verified structured fields; quarantined notices are restored only after human approval |
| **Autonomy level** | 3 · Agent loop |
| **Hard limits** | 6 steps, 45 s, 25k tokens |
| **Human approval before** | Restoring a quarantined notice, permanently excluding or deleting it, or modifying shield rules |

**Decision rule.** *Workflow*: the steps are known in advance and always the same (code fixes them, the LLM only writes). *Agent*: the LLM chooses the tools and the number of steps depending on what it finds.

## 5 real requests

| # | User request | Decision | Justification (one sentence) | Tools |
|---|---|---|---|---|
| 1 | « Quelle est la date limite de réponse de l'avis ao_01 ? » | **Workflow** | The steps never change (search, read, answer with a source, check the date), so the code can fix them. | `search_notices` |
| 2 | « Quels avis ont une date limite avant le 18 avril 2015 ? » | **Workflow** | One deterministic call on the structured deadline field, then a formatted answer, with no choice left to the model. | `list_deadlines` |
| 3 | « Le texte de l'avis ao_02 dit quelque chose d'étrange sur sa date limite. Peut-on s'y fier ? » | **Agent** | The model must decide whether to read the notice, compare the text with the structured field, or search other notices, depending on what it finds. | `get_notice`, `verify_values`, `search_notices` |
| 4 | « L'avis ao_05 me semble suspect : enquête, et mets-le de côté s'il est piégé. » | **Agent** | The model investigates, decides whether the evidence justifies quarantine, and chooses what to write in the incident report, so the path depends on the findings. | `get_notice`, `verify_values`, `quarantine_notice`, `save_incident_report`, `list_quarantined_notices` |
| 5 | « Compare les avis ao_02 et ao_03 : lequel répondre en premier, et leurs dates sont-elles fiables ? » | **Agent** | The model must open several notices, verify each date and weigh the results, which a fixed chain of steps cannot anticipate. | `get_notice`, `verify_values`, `list_deadlines` |

## Summary

- **Workflows:** 2 (requests 1 and 2). **Agents:** 3 (requests 3, 4 and 5).
- **Write actions** (requests 4): `quarantine_notice` and `save_incident_report` change the system state, so the quarantine is temporary and reversible, and any restore, deletion or change of shield rules needs human approval.
- **Security link:** notices are untrusted data. The agent never treats a sentence inside a notice as an order.
