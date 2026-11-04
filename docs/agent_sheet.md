# Agent sheet · ShieldLoop (S1)

| Field | Value |
|---|---|
| **Gen AI product** | RAG assistant over BOAMP public tender notices (BM25 + gpt-oss-20b on Groq), protected against indirect prompt injection |
| **Goal** | Answer purchasing questions from cited notices, investigate suspicious content, and temporarily quarantine notices pending human review |
| **Read tools** | `search_notices`, `get_notice`, `verify_values`, `list_deadlines`, `list_quarantined_notices` |
| **Write tools** | `quarantine_notice` (exclude a notice from retrieval, save evidence) · `save_incident_report` (record findings for review) |
| **Success check** | Answers correct and cited; suspicious notices excluded and logged; deadlines taken from verified structured fields; restores only after human approval |
| **Autonomy** |  Agent loop |
| **Hard limits** | 5 steps |
| **Human approval before** | Restoring, permanently excluding or deleting a notice; changing shield rules |


## 5 requests

| # | Request | Type | Why | Tools |
|---|---|---|---|---|
| 1 | "What is the response deadline of notice ao_01?" | **Workflow** | Same fixed steps every time: search, read, answer with source, check the date. | `search_notices` |
| 2 | "Which notices have a deadline before 18 April 2015?" | **Workflow** | One deterministic filter on the structured deadline field, no model decision. | `list_deadlines` |
| 3 | "Notice ao_02 says something odd about its deadline. Can we trust it?" | **Agent** | The model decides whether to compare the text with the structured field or search other notices, depending on what it finds. | `get_notice`, `verify_values`, `search_notices` |
| 4 | "Notice ao_05 looks suspicious: investigate it and set it aside if it is poisoned." | **Agent** | The model weighs the evidence, decides on quarantine, and writes the report, so the path depends on the findings. | `get_notice`, `verify_values`, `quarantine_notice`, `save_incident_report` |
| 5 | "Compare ao_02 and ao_03: which should we answer first, and are their dates reliable?" | **Agent** | The model must open several notices, verify each date and weigh the results, which a fixed chain cannot anticipate. | `get_notice`, `verify_values`, `list_deadlines` |

**Result:** 2 workflows, 3 agents. Notices are untrusted data: the agent never treats a sentence inside a notice as an order.
