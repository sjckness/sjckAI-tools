# Validazione a due livelli

La validazione di un nodo ha due livelli. Il secondo costa token: parte solo
quando serve.

1. **Livello 1, deterministico** (`sjck-graph/scripts/checks.py`). Esegue i
   criteri eseguibili di `## Criteri di accettazione`.
2. **Livello 2, LLM** (`sjck-graph/agents/sjck-validator.md`). Controlla scope,
   interfacce e criteri non eseguibili leggendo il diff.

| esito livello 1 | cosa succede |
| :- | :- |
| `pass` | nodo `validated`; l'LLM non parte (salvo `validator: llm` nella card) |
| `fail` | l'LLM **non** parte; il nodo torna all'implementer con `output` dei comandi |
| `ambiguous` | parte il validatore LLM |

`ambiguous` = nessun criterio eseguibile, oppure un esito atteso non
interpretabile. Un controllo assente non è un controllo superato. Se c'è un
`fail` e anche un `ambiguous`, vince `fail`.

## Formato dei criteri eseguibili

```
- `python3 -m unittest discover -s tests` → exit 0
- `ruff check .` → 0 fallimenti
```

`` `comando` `` + freccia (`→` o `->`) + esito atteso. Riconosciuti: `exit N`,
`0 fallimenti`/`0 failures`/`0 errori`, `ok`, `pass`; esito vuoto = exit 0. Gli
item senza comando e freccia sono prosa e restano al livello 2. Per forzare il
livello 2 anche su `pass`, aggiungi nei criteri la riga `- validator: llm`.

## CLI

`python3 checks.py run <ID> --cwd .` stampa un JSON (`outcome`, `checks`,
`output`, `llm_required`, `invoke_llm`, `model`) ed esce con 0 pass, 1 fail,
2 ambiguous. `checks.py model` stampa il modello del validatore.

## Modello del validatore

`sjck-graph/config/validation.json` è il default versionato; `.sjck/validation.json`
nel progetto lo sovrascrive (chiavi: `model`, `timeout`). `model` ∈
haiku|sonnet|opus|fable|inherit; un modello più piccolo (`haiku`) è ammesso.
L'orchestratore lo passa come override al lancio del validatore.
