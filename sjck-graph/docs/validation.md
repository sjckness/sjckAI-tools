# Validazione a due livelli (P3)

Prima la validazione era una sola: un subagente LLM (`sjck-validator`,
sonnet/high) dopo ogni nodo, il cui primo compito era rieseguire i comandi dei
criteri di accettazione che l'implementer aveva già eseguito. Ora i due livelli
sono separati.

1. **Livello 1, deterministico** (`sjck-graph/scripts/checks.py`): esegue i
   criteri eseguibili di `## Criteri di accettazione` e controlla lo scope sul
   diff git.
2. **Livello 2, LLM** (`sjck-graph/agents/sjck-validator.md`): giudica i criteri
   che il livello 1 non ha potuto eseguire, lo scope e le regressioni ovvie.

## Livello 1 — `checks.py`, deterministico e gratis

```bash
python3 sjck-graph/scripts/checks.py run T01 --cwd . --base <sha>   # -> .sjck/out/T01.l1.json
```

| esito livello 1 | exit | cosa succede |
| :- | :- | :- |
| `pass` | 0 | tutti i criteri sono eseguibili e verdi, scope dentro la card: nodo `validated`; l'LLM non parte (salvo `validator: llm` o `always_llm`) |
| `fail` | 1 | l'LLM **non** parte; il nodo torna all'implementer con l'`output` dei comandi |
| `ambiguous` | 2 | parte il validatore LLM, che riceve `green` e `residual` |
| configurazione non valida | 3 | non è un `fail` del nodo: si corregge la configurazione |

`ambiguous` = nessun criterio eseguibile, **oppure** resta almeno un criterio
non eseguibile (prosa, esito con "oppure", esito non riconosciuto), **oppure**
lo scope non è pulito o non è verificabile. Il livello 1 non assolve mai ciò che
non ha controllato. Se c'è un `fail` e anche un `ambiguous`, vince `fail`.

Il risparmio viene dal **non rieseguire i test**, non dal saltare il
validatore: il livello 2 riceve `green` (comandi già verdi, da non rilanciare)
e `residual` (i soli criteri da giudicare), anche in `.sjck/out/<ID>.l1.json`.
La decisione `invoke_llm` è una sola funzione (`decide`) usata da CLI e `validate()`.

### Formato dei criteri eseguibili

```
- `python3 -m unittest discover -s tests` → exit 0
- `ruff check .` → 0 fallimenti
```

`` `comando` `` + freccia (`→` o `->`) + esito atteso. Riconosciuti: `exit N`,
`0 fallimenti`/`0 failures`/`0 errori`, `ok`, `pass`; esito vuoto = exit 0. Gli
item senza comando e freccia sono prosa e restano al livello 2. Per forzare il
livello 2 anche su `pass`, aggiungi nei criteri la riga `- validator: llm`.

### Scope-check

Il livello 1 confronta `git diff --name-only <base>` (più i file non tracciati,
letti prima di eseguire i comandi; `.sjck/` ignorata) con i percorsi di
`## Puoi modificare`. `<base>` è `checks.py run --base <sha>`: il commit a cui il
nodo è partito, che l'orchestratore registra al lancio e passa qui. Se il diff
tocca altro, l'esito diventa `ambiguous` anche con tutti i comandi verdi (mai
`fail`: non è un criterio della card), `out_of_scope` elenca i file, `residual`
ne dà la voce `scope:` e parte il livello 2.

Se lo scope **non è verificabile** (manca `## Puoi modificare`, non è un repo
git, `--base` non esiste) l'esito è `ambiguous` con la voce `scope: non
verificabile`: un controllo che non si può fare non è un controllo superato.

## Livello 2 — il validatore LLM, con modello configurabile

Il validatore parte solo su `ambiguous` (o su richiesta della card) e riceve dal
`.l1.json` ciò che è già stato verificato: non rieseguire i comandi in `green`,
giudicare le voci di `residual`, lo scope e le regressioni. La card gli arriva
ridotta al suo ruolo (`context.py card --id <ID> --role validator`: senza la
sezione "Leggi").

Modello ed effort del livello 2 (default `sonnet`/`high`, come il frontmatter
dell'agente), in ordine di precedenza:

```bash
# progetto
echo '{"validator": {"model": "haiku", "effort": "low"}}' > .sjck/config.json
# utente: ~/.sjck/config.json ; esplicito: $SJCK_CONFIG
export SJCK_VALIDATOR_MODEL=haiku SJCK_VALIDATOR_EFFORT=low   # vincono su tutto
python3 sjck-graph/scripts/config.py validator                # configurazione effettiva
```

Sezione `validator` completa: `model` (haiku|sonnet|opus|fable|inherit),
`effort` (low|medium|high|xhigh|max), `timeout_s` (per comando del livello 1,
default 300), `always_llm` (tiene sempre il livello 2). Il valore risolto finisce
nei campi `model`/`effort` del `.l1.json`: l'orchestratore lo passa come override
al lancio. Senza override vince il frontmatter di `sjck-validator.md` e la
configurazione **non ha effetto**; vale per le modalità S, M e L. Un valore non
valido fa uscire `checks.py` con 3 e un messaggio su stderr.

Quando conviene un modello piccolo: criteri quasi tutti deterministici, nodi
meccanici, repo con test veloci. Quando no: criteri scritti a parole, nodi
rischiosi (concorrenza, formati, sicurezza). `always_llm: true` riporta il
comportamento di prima.

## Affidabilità

Un `pass` del livello 1 richiede che **tutti** i criteri della card siano
comandi, che passino, e che il diff resti dentro la card. Un criterio a parole
porta sempre al livello 2, quindi il taglio non riguarda i nodi con criteri
vaghi. Il plan score già rifiuta le card senza criteri
(`sjck-graph/scripts/plan_score.py:162`), e una card senza criteri finisce
comunque in `ambiguous`, non in `pass`.

## Limiti

- I comandi girano in una **shell** nella cartella del run: chi scrive una card
  può eseguire codice. È lo stesso potere che ha oggi l'agente che li esegue,
  ma ora senza un LLM in mezzo: le card che arrivano da una change request
  vanno lette prima di avviare il run.
- Senza `--base` il confronto è con HEAD: i commit fatti dal nodo (le card
  chiedono `git commit --only`) non compaiono nel diff e un file fuori scope già
  committato non si vede; per questo l'orchestratore deve passare `--base`. Con
  nodi paralleli sullo stesso working tree il diff include anche i file degli
  altri nodi: l'esito è più prudente (`ambiguous`), mai più permissivo.
- Un test che passa non dice che il nodo ha fatto la cosa giusta: resta la
  review finale (`sjck-reviewer`) in modalità L.
- Il livello 1 non controlla stub vuoti, TODO e test disattivati (controllo 4
  del validatore): se la card non lo chiede come criterio a parole, nessuno lo
  verifica — e un criterio a parole fa partire il livello 2.
