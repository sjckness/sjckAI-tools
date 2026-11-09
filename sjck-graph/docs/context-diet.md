# Dieta del contesto (P2)

`tokens.py` stima da dove viene l'input di ogni nodo: `system`, `card`,
`interfaces`, `file_read_in_card`, `file_read_outside_card`, `tool_output`,
`agent_messages`, `thinking`, `reminders`, `other`. `context.py` usa quelle
categorie per decidere dove tagliare, e taglia.

## Quali due categorie attaccare

```bash
python3 sjck-graph/scripts/context.py top --cwd .      # due più pesanti + intervento
```

Sul run di esempio (`examples/demo`, 7 nodi, 418k token di input+cache) escono
`system` 31,6% e `file_read_in_card` 19,1%.

- **`system`** è il costo d'avvio di un subagente (prompt di sistema,
  definizione dell'agente, definizioni dei tool): 15-21k per nodo, pagati una
  volta per lancio. Non si riduce con card migliori: si riduce **lanciando meno
  subagenti**.
- **`file_read_in_card`** sono i file che la card autorizza a leggere: si
  pagano di nuovo a ogni agente nuovo che li rilegge.

## Interventi

### 1. Interfacce riusate per hash — colpisce `system` e `file_read_in_card`

Quando lo scout scrive `.sjck/interfaces/<nome>.md`, l'orchestratore registra
l'hash dei file da cui l'ha estratta:

```bash
python3 .../context.py interfaces record --name api --from-card T00 --cwd .
```

Al run successivo, se quei file non sono cambiati, il nodo scout non parte:

```bash
python3 .../context.py interfaces skip --cwd .    # {"reusable": [{"id": "T00", ...}]}
python3 .../context.py interfaces check --name api   # fresh | stale | missing
python3 .../context.py interfaces reuse --name api   # ripesca anche da .sjck/archive/
```

Una voce di cartella nella sezione "Leggi" viene espansa nei suoi file: un file
aggiunto o cambiato rende l'interfaccia `stale`. Oltre 400 file l'hash è
parziale e lo dichiara (`partial: true`).

Risparmio atteso: un nodo scout saltato = un avvio a freddo in meno (15-21k
token di `system` nel run di esempio) più le sue letture (`file_read_in_card`).
Nel run di esempio il nodo scout T00 vale 38k token: ~9% del run. Si ottiene
solo dal secondo run in poi, e solo se i file sorgente non sono cambiati.

### 2. Card per ruolo — colpisce `card`

```bash
python3 .../context.py card --id T01 --role validator --cwd .
```

Il validatore riceve Obiettivo, Puoi modificare, Criteri di accettazione e
Fuori scope: non la sezione "Leggi", che è l'elenco di file per l'implementer,
e non "Correzioni richieste" se non è un ritentativo (`--attempt N`). Il critico
riceve solo Obiettivo e Criteri.

Risparmio atteso: `card` è 6,7% del run di esempio e viene pagata 2-3 volte per
nodo (implementer, validatore, retry). Il taglio è il peso delle sezioni non
pertinenti, tipicamente 30-50% della card per il validatore: ordine di
grandezza 1-2% del run. Piccolo, ma a rischio zero.

Correlato: `context.py state --id T01` dà goal + nodo + deps invece di tutto
`state.json`, per quando un nodo ha bisogno di sapere com'è andata una dep.

### 3. Prompt con la parte stabile in testa — colpisce la prompt cache

```bash
python3 .../context.py prompt --id T01 --role implementer --script /abs/scripts
```

La cache dei prompt funziona per prefisso: tutto ciò che è identico fra due
lanci si paga come cache read (circa un decimo dell'input) invece che come
input. `prompt` mette in testa ciò che non cambia da nodo a nodo (ruolo,
percorso degli script, contratto) e dopo il separatore `--- nodo ---` ciò che
cambia (ID, budget, tentativo, card).

Risparmio atteso: il prefisso stabile è piccolo (2-400 token), quindi il
guadagno diretto è dell'ordine dell'1%; conta soprattutto perché evita il
contrario, cioè un prompt che cambia in testa e invalida la cache del nodo per
tutti i turni successivi (l'insight `cache` di `token-report.json` misura
proprio questo).

## Limiti

- Le categorie sono **stime** (`categories_estimated: true` in tokens.json):
  servono a ordinare gli interventi, non a certificare un risparmio.
- `interfaces skip` si fida della card: un nodo scout che legge file non
  elencati in "Leggi" può essere saltato a torto. Per questo la card dello
  scout deve elencare i sorgenti (vedi `agents/sjck-planner.md`).
- Gli hash sono per contenuto: un file riformattato senza cambi di sostanza
  rende comunque l'interfaccia `stale`.
- `context.py` non lancia e non ferma nulla: decide l'orchestratore.
