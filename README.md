# WatchLog

Registro dei film visti da un gruppo di amici, con le statistiche per utente e di gruppo.
Oggi si alimenta importando l'export di una chat WhatsApp, che contiene un messaggio per ogni visione.
Per ogni film cerca i metadati su TMDB (durata, generi, regista) e salva la visione per l'utente che l'ha scritta.
Un bot Discord registra le visioni scritte in un canale e risponde al comando `/stats` con le statistiche.

Tutti i comandi si lanciano con `watchlog` e hanno l'opzione `--help`, per esempio `watchlog stats --help`.

## Installazione

Serve Python 3.12 o superiore.

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Negli esempi qui sotto `watchlog` sta per `.venv/bin/watchlog`, oppure per `watchlog` dopo `source .venv/bin/activate`.

## Configurazione

I file con i dati reali sono ignorati da git: stanno in `local/`, `data/` e `config/`.

| Cosa | Dove | Note |
|---|---|---|
| Chiave TMDB | `local/tmdb_api_key`, oppure variabile `TMDB_API_KEY` | Va bene la chiave API v3 (32 caratteri) o il token di lettura (stringa lunga che inizia con `eyJ`). Si ottengono gratis su themoviedb.org, nelle impostazioni del profilo, sezione API. |
| Export della chat | `local/chat.txt` | Si ottiene con la funzione "Esporta chat" di WhatsApp, senza media. Vanno bene i formati Android e iPhone. |
| Utenti | `config/users.yaml` | Parti da `config/users.example.yaml`. |
| Correzioni dei film | `config/corrections.yaml` | Facoltativo. Parti da `config/corrections.example.yaml`. |
| Database | `data/watchlog.sqlite` | Creato dal primo import. |
| Token del bot Discord | `local/discord_token`, oppure variabile `DISCORD_TOKEN` | Solo per il comando `bot`. |
| Server e canali Discord | `config/discord.yaml` | Solo per il comando `bot`. Parti da `config/discord.example.yaml`. |

Per il bot Discord: la guida per creare l'app e il token è in [docs/discord-app.md](docs/discord-app.md), quella per installarlo sul Synology in [docs/deploy-synology.md](docs/deploy-synology.md).

Esempio di `config/users.yaml`:

```yaml
users:
  - name: mario                # nome interno, a tua scelta
    whatsapp: "Mario Rossi"    # identico al nome nell'export della chat
    discord_id: 123456789012345678   # facoltativo, si aggiunge quando l'utente si iscrive a Discord
  - name: franco
    whatsapp: "Franco Rossi"
```

## Formato dei messaggi

Ogni visione è un messaggio come questo:

```
05/07/2026 - Maledetto il giorno che t'ho incontrato (1992)
05/07/2026 - Heat (1995) [4.5]
```

- La **data** è quella in cui hai visto il film, non quella in cui hai scritto il messaggio.
- L'**anno** tra parentesi è obbligatorio: serve a distinguere i film con lo stesso titolo.
- Il **voto** tra parentesi quadre è facoltativo: da 0,5 a 5, a passi di 0,5, con punto o virgola.
- Se la data manca, o è sbagliata (`0000`, `31/02/2026`, `05/07/26`), si usa la data d'invio del messaggio. Quando era sbagliata, la riga compare tra le anomalie.
- Un titolo spezzato su due righe viene riunito, e un trattino dentro il titolo non dà problemi.
- Le righe che non sono visioni (conversazione, messaggi di sistema, messaggi cancellati) vengono ignorate, oppure segnalate come anomalie.

## Comandi

### `parse`: leggere la chat, senza rete né database

Utile per controllare cosa capisce il parser prima di importare.

```
watchlog parse local/chat.txt
```

Stampa una riga per ogni visione (data di visione, autore, titolo e anno), poi le eventuali anomalie e un riepilogo con il numero di visualizzazioni e di anomalie.
Accanto alla data, tra parentesi, c'è la sua provenienza: `body` se viene dal messaggio, `sent_at` se è il ripiego sulla data d'invio.

### `resolve`: cercare un film su TMDB

```
watchlog resolve "Roofman (2026)"
watchlog resolve "In the Lost Landa (2025)"
```

L'esito può essere:
- `resolved`: un solo film convincente. L'anno può differire di uno, perché l'uscita italiana è spesso in un anno diverso da quella originale.
- `ambiguous`: più candidati, o uno solo ma poco simile. Vengono elencati con il loro id.
- `not_found`: nessun candidato. Di solito c'è un refuso, perché la ricerca di TMDB non tollera errori nel titolo.

`resolve-chat local/chat.txt` fa lo stesso per tutti i film distinti di un export e stampa un riepilogo.

### `import`: salvare le visioni nel database

Prima simula, poi importa davvero.

```
watchlog import local/chat.txt --dry-run
watchlog import local/chat.txt
```

Il dry-run esegue lo stesso codice dell'import su una copia del database in memoria: non scrive nulla su disco, ma interroga TMDB.
Il report riporta le visualizzazioni nel file, quelle inserite, quelle già presenti e i film nuovi.
Può inoltre contenere queste sezioni:
- **Utenti non mappati**: aggiungili a `config/users.yaml`.
- **Film da risolvere**: vedi più sotto, "Compilare `corrections.yaml`".
- **Date sospette**: righe con la data del messaggio più di 31 giorni prima dell'invio, o dopo. Di solito è un refuso nell'anno. Le righe vengono importate lo stesso.
- **Anomalie del parser**: righe che non sono visioni, o con la data sbagliata.

Opzioni: `--db`, `--users` e `--corrections` cambiano i percorsi predefiniti (`data/watchlog.sqlite`, `config/users.yaml`, `config/corrections.yaml`).

Cose da sapere:
- **Si può rilanciare in sicurezza.** Le righe già importate vengono riconosciute e non duplicate, e non fanno più chiamate a TMDB.
- **È atomico.** Se TMDB fallisce a metà, non viene salvato nulla.
- **Un messaggio modificato dopo l'import** e poi riesportato viene visto come una visione nuova, perché l'export non ha un identificativo del messaggio.
- **Le righe già importate non si aggiornano.** Se correggi una data nella chat e rilanci l'import, il database non cambia. Finché il database deriva solo dalla chat, la strada più semplice è fare una copia di `data/watchlog.sqlite`, cancellarlo e reimportare.

### `stats`: le statistiche

```
watchlog stats                                              # tutto il gruppo
watchlog stats --user franco                                # un utente (nome interno)
watchlog stats --dal 2026-08-01 --al 2026-08-31             # un periodo, estremi inclusi
watchlog stats --user franco --dal 2026-08-01               # le opzioni si combinano
```

Il periodo si applica alla data di visione ed è valido per ogni numero del report.

Il report contiene i totali (visualizzazioni, film distinti, rivisioni, tempo totale, durata media, film più lungo e più corto, serie consecutiva più lunga, voto medio), i generi e i registi più visti, i decenni di uscita, le visualizzazioni e le ore per mese, i giorni della settimana e i giorni con più film.
Per il gruppo si aggiungono la classifica degli utenti, i film più visti e quelli visti da tutti.

Cosa significano i numeri:
- **Rivisioni**: visioni di un film che lo *stesso utente* aveva già visto. Due utenti che vedono lo stesso film non contano.
- **Serie consecutiva**: giorni di calendario di fila con almeno una visione. Più visioni nello stesso giorno contano una volta. Per il gruppo conta qualunque utente.
- **Giorni della settimana** e **mesi**: usano la data di visione scritta in chat.
- **Tempo e durata media**: le visioni di film senza durata su TMDB non entrano nel conto, e il report lo dice.
- **Voto medio**: considera solo le visioni votate. Lo storico di WhatsApp non ha voti, quindi compare quando ci saranno.
- **Film visti da tutti**: compare solo se gli utenti con visioni sono almeno due, e conta chi ha almeno una visione nel periodo scelto.

### `bot`: il bot Discord

```
watchlog bot
```

Collega il bot al server e resta in ascolto finché non lo fermi con Ctrl+C.
Serve il token in `local/discord_token` e `config/discord.yaml` con gli ID del server, del canale delle statistiche e, per l'inserimento, del canale delle visioni.
L'inserimento usa anche la chiave TMDB: se manca la chiave, o manca `input_channel_id`, il bot parte lo stesso e disattiva solo l'inserimento.
Opzioni: `--db`, `--discord-config` e `--users` cambiano i percorsi predefiniti.
All'avvio il bot applica `config/users.yaml` al database: i nomi interni e i `discord_id` modificati nel file diventano effettivi riavviando il bot, senza rifare l'import.
I nomi mostrati nel completamento del parametro `utente` sono i nomi interni di `users.yaml`, quindi per usare i nomi di Discord basta scriverli lì.

Nel canale delle visioni si scrive un film per messaggio, nello stesso formato della chat WhatsApp: `05/07/2026 - Heat (1995)`, con voto facoltativo `[4.5]`.
La data può mancare: si usa quella del messaggio. L'utente che scrive deve avere il `discord_id` in `config/users.yaml`.
Il bot risponde così:
- ✅ e un messaggio con ciò che ha salvato, indicando la data usata.
- Dei bottoni, se il film è ambiguo o poco sicuro: può scegliere solo chi ha scritto, entro 3 minuti. «Nessuno di questi» annulla.
- Due bottoni di conferma, se hai già registrato lo stesso film nello stesso giorno.
- ❌ e un messaggio, se non trova il film o il voto non è valido.
- ❓, senza testo, se il messaggio non ha il formato di una visione: nel canale si può anche chiacchierare.
Un messaggio modificato o cancellato dopo la registrazione non cambia nulla.

Nel canale delle statistiche si usa il comando `/stats`, con tre parametri facoltativi:
- `utente`: il nome interno di un utente, con completamento automatico. Senza, il report è del gruppo.
- `periodo`: una scorciatoia tra oggi, questa settimana (da lunedì a domenica), questo mese e quest'anno.
- `dal` e `al`: il periodo, in formato `AAAA-MM-GG`, estremi inclusi. Non si combinano con `periodo`: il bot lo segnala.

Il contenuto è lo stesso del comando `stats`, in messaggi da blocco di codice (se il report è lungo arriva in più messaggi).

Sempre nel canale delle statistiche, `/visioni` mostra l'elenco delle singole visioni, dalla più recente.
Ha gli stessi parametri facoltativi di `/stats` (`utente`, `periodo`, `dal` e `al`) e se ne aggiunge uno:
- `titolo`: solo i film il cui titolo contiene quel testo, senza badare a maiuscole e accenti; vale anche per il titolo originale.

Ogni riga ha il numero della visione, la data, l'utente (se l'elenco è di gruppo), titolo, anno e voto.
Le righe sono 20 per pagina: con più visioni compaiono i bottoni «Precedente» e «Successivo», che può usare solo chi ha lanciato il comando.
Le visioni annullate non compaiono.

In un altro canale il bot risponde, solo a chi ha scritto, indicando il canale giusto.
Gli errori (utente sconosciuto, data non valida) sono visibili solo a chi ha lanciato il comando.
Per ogni token deve girare una sola istanza del bot.

## Flusso di lavoro consigliato

1. Esporta la chat e mettila in `local/chat.txt`.
2. Compila `config/users.yaml` con un utente per ogni nome della chat.
3. Lancia `watchlog import local/chat.txt --dry-run` e leggi il report.
4. Aggiungi gli utenti mancanti e compila `config/corrections.yaml` (vedi sotto). Ripeti dal punto 3 finché il report non ha più sezioni da sistemare.
5. Lancia `watchlog import local/chat.txt` e poi `watchlog stats`.
6. Per aggiornare lo storico, esporta di nuovo la chat e rilancia l'import: verranno aggiunte solo le visioni nuove.

### Compilare `corrections.yaml`

Il file associa un titolo, scritto come in chat, al film giusto di TMDB.
Ogni voce ha `title` e `year` (come nella riga della chat, senza badare a maiuscole e punteggiatura) e `tmdb_id`.

```yaml
corrections:
  - {title: "Il Sesto Senso", year: 1999, tmdb_id: 745}  # The Sixth Sense - Il sesto senso (1999)
  - {title: "Man in Black", year: 1997, tmdb_id: 607}    # Men in Black (1997)
```

Il report dell'import ti suggerisce già le righe, in tre forme:
- **Riga attiva con id**: c'era un solo candidato. Controlla il titolo nel commento: se è sbagliato, cancella la riga.
- **Riga commentata con `???` e un elenco "scegli"**: più candidati con lo stesso titolo e anno. Scegli l'id (regista e durata si vedono sulla scheda TMDB), poi togli il `#` e sostituisci `???`.
- **Riga commentata con "non trovato su TMDB"**: cerca il film su themoviedb.org. L'id è il numero nell'URL, per esempio `.../movie/438631-dune` dà `438631`. Controlla che anno e film siano quelli giusti.

## Risoluzione dei problemi

| Messaggio | Cosa fare |
|---|---|
| `Chiave TMDB mancante` | Salva la chiave in `local/tmdb_api_key` o in `TMDB_API_KEY`. |
| `chiave TMDB non valida` | Controlla di averla copiata per intero. Il token di lettura è molto lungo. |
| `TMDB ha risposto 429` | Troppe richieste ravvicinate. Aspetta qualche secondo e rilancia: l'import è atomico e non lascia dati a metà. |
| `File non trovato: config/users.yaml` | Crealo con il comando `cp` che il messaggio suggerisce. |
| `Database non trovato` | Lancia prima un import vero: il dry-run non crea il database. |
| Un film finisce sempre tra quelli da risolvere | Aggiungi una voce a `config/corrections.yaml`. |

## Test

```
.venv/bin/pytest
```

I test non usano la rete: TMDB è simulato.
Il campione `tests/fixtures/sample_chat.txt` contiene nomi di fantasia ed è usato dai test.
