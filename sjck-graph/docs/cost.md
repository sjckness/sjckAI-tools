# Costo di un run in dollari (P1)

`tokens.py` raccoglie i token reali dai transcript; da questa versione scrive
anche il **costo**, per run, per nodo (quindi per agente) e per modello, in
`.sjck/tokens.json` e `.sjck/token-report.json`.

## Due fonti, una delle quali è una stima

| fonte | quando | marcatura |
| :- | :- | :- |
| `cost-state` | il transcript della sessione contiene l'evento di costo scritto da Claude Code | `cost.estimated: false`, `source: "cost-state"` |
| listino prezzi | sempre il resto del tempo (run in corso, transcript senza quell'evento) | `cost.estimated: true`, `source: "prices"` |

`cost-state` è un totale **di sessione**: va ripartito sui nodi. La ripartizione
usa il costo per nodo calcolato dal listino quando il listino copre tutti i nodi
(`split: "per-node shares from prices.json"`), altrimenti i rapporti di prezzo
tra i tipi di token, come prima. Quando esiste il costo reale, la stima resta
accanto come `cost.estimate_usd`: il confronto dice se il listino è aggiornato.

## Il listino

File distribuito: `sjck-graph/scripts/prices.json`. USD per milione di token.

```json
{
 "updated": "2026-11-09",
 "cache_multipliers": {"cache_read": 0.1, "cache_creation": 1.25},
 "models": {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2}}
}
```

- `input` e `output` sono obbligatori.
- **cache read** e **cache write** si ricavano dai moltiplicatori rispetto
  all'input (0,1 e 1,25). Un modello può dichiarare un prezzo esplicito
  `cache_read` / `cache_write`, che vince sul moltiplicatore: è il caso di
  diversi modelli recenti.
- `cache write` è la cache a 5 minuti. Quella a 1 ora costa di più: se la usi,
  alza il moltiplicatore nel tuo override.

### Override senza toccare il codice

L'ultimo che parla vince, e si fondono campo per campo:

1. `sjck-graph/scripts/prices.json` (distribuito col kit)
2. `~/.sjck/prices.json` (tuo, per tutti i progetti)
3. `<progetto>/.sjck/prices.json` (del run)
4. `$SJCK_PRICES=/percorso/listino.json`

```bash
# sconto negoziato solo su un progetto
echo '{"models": {"claude-opus-5-5": {"input": 3.2, "output": 16.0}}}' > .sjck/prices.json
python3 sjck-graph/scripts/config.py prices --model claude-opus-5-5   # verifica
```

Mettere un modello a `null` lo toglie dal listino: per quel modello il kit
mostra **solo i token**. Un modello che non è in tabella non ha un prezzo
inventato: finisce in `cost.unpriced_models` e i suoi nodi restano senza
`cost_usd`. Bedrock e Vertex hanno listini propri: vanno messi in un override.

## Cosa trovi nei file

`.sjck/tokens.json`

```json
{"cost": {"usd": 1.84, "eur": 1.71, "source": "prices", "estimated": true,
          "by_model": {"claude-sonnet-5-5": 1.2}, "prices_updated": "2026-11-09",
          "unpriced_models": []},
 "by_node": {"T01": {"total": 52000, "cost_usd": 0.41, "cost_estimated": true,
                     "cost_eur": 0.38}},
 "by_model": {"claude-sonnet-5-5": {"total": 310000, "cost_usd": 1.2}}}
```

`.sjck/token-report.json`: blocco `cost` (totale, per nodo, per modello,
`estimated`) e, su ogni insight, `cost_usd` del nodo e `saving_usd`, cioè i
token risparmiabili valorizzati col prezzo medio di quel nodo. `saving_usd`
negativo = risparmio già ottenuto.

Gli euro restano come prima: tasso di riferimento BCE, cache giornaliera in
`~/.sjck/fx.json`, override `SJCK_EUR_PER_USD`, `SJCK_FX_OFFLINE=1` per non
chiamare nessuno.

## Limiti

- La stima vale quanto il listino: se i prezzi cambiano e nessuno aggiorna il
  file, il numero è vecchio. `prices_updated` dice di quando è.
- Cache a 1 ora, prompt lunghi con scaglioni (es. oltre 100k token su alcuni
  modelli), fast mode e batch non sono modellati: un moltiplicatore unico per
  modello non li distingue.
- Il costo per nodo eredita l'attribuzione dei token: un subagente non
  collegabile al suo nodo resta in `unattributed`.
- `output` dei subagenti è ricostruito quando il transcript non ha la riga
  finale (±6% misurato): il costo ne eredita l'errore.
