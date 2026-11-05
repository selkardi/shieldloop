\# S4: strategy and memory



1\. Strategy: ReAct loop (think, call one tool, read the result, decide the next step), capped at 4 steps, because the next step depends on what the notices contain.

2\. Reflection: before answering, one self-check with verify\_values (every date or figure must appear in the cited notice); if unsupported, correct it or answer NOT FOUND.

3\. Why not plan-and-execute: a plan written before reading the notices cannot adapt to what is found (alerts, missing notice, ambiguous dates).

4\. Short-term memory (one request only): the question and the cleaned passages returned by the shield; the isolated suspicious lines are never put back in context.

5\. Long-term memory: only the quarantine registry (registry.json plus evidence files), written by quarantine\_notice after human approval and kept until a human reviews it; no chat history and no notice text is stored. Reading the registry inside the search step is the next step.

