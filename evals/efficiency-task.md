# Task: efficienza in token del kit sjck-graph

Questo repo contiene sjck-graph, un plugin di Claude Code che orchestra agenti
come un grafo di nodi (scout, implementer, validator, reviewer, critic) con un
file di stato `.sjck/state.json`. Obiettivo: **ridurre il costo in token di un
run senza ridurne l'affidabilità**.

## Fase 1 — Analisi (prima di modificare qualsiasi file)

Leggi agenti, skill, hook e `sjck-graph/scripts/tokens.py`. Individua dove un
run spreca token: contesto passato ai nodi, letture ripetute, validatori,
scelta del modello. Scrivi l'analisi nella sezione "Analisi" di
`EFFICIENCY-REPORT.md`, con evidenze nel formato `percorso:riga`.

## Fase 2 — Implementa questi tre miglioramenti

La rubrica è fissa. Se l'analisi trova sprechi più grandi, annotali nella
sezione "Altri sprechi" del report, ma non implementarli.

**P1 — Costo in dollari per nodo, agente e run.**
`tokens.py` raccoglie già i token; aggiungi il costo in USD in
`.sjck/tokens.json` e `.sjck/token-report.json`.
- Prezzi per modello in un file di configurazione modificabile, con override
  senza toccare il codice.
- Cache read e cache write con i rispettivi moltiplicatori rispetto
  all'input normale.
- Se l'evento `cost-state` fornisce il costo reale, usalo; altrimenti stima e
  marca il valore `estimated: true`.

**P2 — Dieta del contesto.**
Usa le categorie già stimate da `tokens.py` (card, interfacce, file dentro e
fuori card, output dei tool, messaggi dei subagenti, system) per individuare
le due categorie più pesanti e ridurle. Esempi di intervento: riuso delle
interfacce estratte dallo scout quando il file non è cambiato (hash), parti
di card e di stato passate ai nodi solo se servono, prompt ordinato con la
parte stabile in testa per sfruttare la prompt cache. Per ogni riduzione,
indica la categoria colpita e il risparmio atteso.

**P3 — Validatori a due livelli.**
Prima i controlli deterministici (test, lint, schema indicati nella card)
eseguiti da script; il validatore LLM parte solo se l'esito è ambiguo o la
card lo richiede. Il modello del validatore deve essere configurabile e
poter essere più piccolo. Test che dimostrino: controllo deterministico
fallito → nessuna chiamata al validatore LLM; modello configurabile.

Per ogni punto servono: implementazione, test unitari, una riga nel
`CHANGELOG.md` e la documentazione necessaria in `docs/`.

## Vincoli

- Python 3.9, solo standard library, nessuna chiamata di rete.
- I test esistenti devono restare verdi:
  `python3 -m unittest discover -s sjck-graph/tests` (138 test al commit di partenza).
- Non modificare `console/` e `vscode/`, salvo necessità dimostrata nel report.
- Non modificare `evals/efficiency-task.md` né `evals/sum_usage.py`.
- Lavora solo sul branch corrente: committa, ma non fare push e non fare merge.
- Non lanciare altri run di sjck per misurare i token: la misura la fa
  `evals/sum_usage.py` dall'esterno.

## Consegna

`EFFICIENCY-REPORT.md` nella root del repo, con:
1. Analisi (evidenze `percorso:riga`).
2. Per ciascun punto P1-P3: cosa è cambiato (file), come si verifica
   (comando esatto), limiti noti.
3. Altri sprechi trovati (non implementati).
