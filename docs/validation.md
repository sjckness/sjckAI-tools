# Validazione a due livelli

La validazione di un nodo ha due livelli. Il secondo costa token: parte solo
quando serve.

1. **Livello 1, deterministico** (`sjck-graph/scripts/checks.py`). Esegue i
   criteri eseguibili di `## Criteri di accettazione`.
2. **Livello 2, LLM** (`sjck-graph/agents/sjck-validator.md`). Controlla scope,
   interfacce e criteri non eseguibili leggendo il diff.

| esito livello 1 | cosa succede |
| :- | :- |
| `pass` | tutti i criteri sono eseguibili e verdi: nodo `validated`; l'LLM non parte (salvo `validator: llm`) |
| `fail` | l'LLM **non** parte; il nodo torna all'implementer con `output` dei comandi |
| `ambiguous` | parte il validatore LLM, che riceve `green` e `residual` |

`ambiguous` = nessun criterio eseguibile, **oppure** resta almeno un criterio
non eseguibile (prosa, esito con "oppure", esito non riconosciuto). Il livello
1 non assolve mai ciò che non ha controllato. Se c'è un `fail` e anche un
`ambiguous`, vince `fail`.

Il risparmio viene dal **non rieseguire i test**, non dal saltare il
validatore: il livello 2 riceve `green` (comandi già verdi, da non rilanciare)
e `residual` (i soli criteri da giudicare), anche in `.sjck/out/<ID>.l1.json`.
La decisione `invoke_llm` è una sola funzione (`decide`) usata da CLI e `validate()`.

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
`output`, `green`, `residual`, `llm_required`, `action`, `invoke_llm`, `model`),
lo salva in `.sjck/out/<ID>.l1.json` ed esce con 0 pass, 1 fail, 2 ambiguous,
3 configurazione non valida (messaggio su stderr). `checks.py model` stampa il modello del validatore.

## Modello del validatore

`sjck-graph/config/validation.json` è il default versionato; `.sjck/validation.json`
nel progetto lo sovrascrive (chiavi: `model`, `timeout`). `model` ∈
haiku|sonnet|opus|fable|inherit; un modello più piccolo (`haiku`) è ammesso.
L'orchestratore lo passa come override al lancio del validatore.
