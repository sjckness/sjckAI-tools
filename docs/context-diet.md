# Dieta del contesto (P2)

Categorie = `CATS` in `sjck-graph/scripts/tokens.py:87`. I risparmi sono
**stime**, non misure: da verificare con `tokens.py` su un run reale.

Le due categorie più pesanti secondo T01: `system` (CLAUDE.md su validator,
reviewer, planner, critic; boilerplate) e `interfaces` / `file_read_outside_card`
(nessun riuso delle interfacce). `omitClaudeMd` sugli agenti non di T03 è
fuori scope: segnalato come finding / handoff a T05.

## Ordine del prompt (stabile)

1. `system` — prompt dell'agente, riga `script:`
2. `fuori scope` — regole sui findings
3. `budget`
4. `card` — dopo, perché cambia per nodo
5. `correzioni` — ultima: cresce a ogni retry senza invalidare il prefisso

Prefisso invariante in testa = hit di prompt cache tra nodi e tentativi.
Implementato da `cards.build_prompt`.

## Riduzioni

| # | Riduzione | Categoria | Risparmio atteso (stima) |
| - | - | - | - |
| 1 | Riuso interfacce via hash (`interfaces.py`) | `interfaces`, `file_read_outside_card` | Uno scout evitato per interfaccia non cambiata: ~ costo intero del nodo scout (alcune migliaia di token); ragionamento: scout rilegge i sorgenti, fresh = 0 letture. |
| 2 | Card e stato selettivi (`select_sections`, `select_state`) | `card` | Il validator non ha bisogno di "Obiettivo"; escludere 1-2 sezioni su 6 e lo stato intero (solo nodo + deps) taglia ~20-40% della card e >80% dello stato su piani grandi. |
| 3 | Ordine del prompt (`build_prompt`) | `system` (+`card`) | Non riduce i token ma li sposta su cache read (~10% del prezzo input): prefisso invariante di centinaia di token riletto ad ogni lancio e retry. |

## Uso

`python3 scripts/interfaces.py check|register|invalidate <nome> [file...]`
(exit 0 = fresh). Lo scout non ha Bash: lo esegue l'orchestratore.
