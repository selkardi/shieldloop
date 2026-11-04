# Local Python / MCP comparison

Synthetic fixtures; simulated approval; no Groq calls.

| Scenario | Local | MCP | Result |
|---|---|---|---|
| Avis inexistant | rejected | rejected | OK |
| Preuve absente du document | rejected | rejected | OK |
| Approbation refusee | rejected | rejected | OK |
| Quarantaine approuvee | quarantined | quarantined | OK |
| Appel repete | already_quarantined | already_quarantined | OK |

Checks compare actual persistence and original preservation, not just status strings.
Timestamps and unique evidence paths are intentionally not compared for equality.
This test checks MCP connection parity, not attack resistance or RAG retrieval integration.