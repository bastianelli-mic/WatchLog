# Installare WatchLog sul Raspberry Pi

Guida passo per passo per far girare WatchLog sul Raspberry Pi 3 in due container con riavvio automatico: il bot Discord e la pagina web.
Le immagini si costruiscono sul Pi stesso, quindi l'architettura ARM non richiede nulla di speciale.
Il build sul Pi non è ancora stato provato: il primo avvio è la verifica.

## Cosa serve

- **Raspberry Pi OS Lite a 64 bit**. Sul Pi, `dpkg --print-architecture` deve rispondere `arm64`: con il sistema a 32 bit (`armhf`) alcune dipendenze non hanno pacchetti pronti.
- Accesso SSH al Pi. Con Raspberry Pi Imager si attiva già nella scrittura della scheda, insieme a utente, password e nome del Pi (per esempio `watchlog`, che in rete diventa `watchlog.local`).
- L'app Discord già creata, con il token in `local/discord_token` (vedi `docs/discord-app.md`).
- La chiave TMDB in `local/tmdb_api_key`, che serve all'inserimento delle visioni dal bot.
- `config/discord.yaml` e `config/users.yaml` compilati, e il database `data/watchlog.sqlite` già importato.

Negli esempi `UTENTE@IP_PI` sta per l'utente creato sul Pi e il suo indirizzo, per esempio `mario@watchlog.local`.

## 1. Installare Docker

Via SSH, sul Pi:

```
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

Cosa fa ogni parte:
- `curl -fsSL URL -o get-docker.sh` scarica lo script ufficiale di installazione di Docker: `-f` fallisce sugli errori HTTP, `-sS` nasconde l'avanzamento ma non gli errori, `-L` segue i reindirizzamenti, `-o` salva nel file indicato. Prima di lanciarlo lo puoi leggere con `less get-docker.sh`.
- `sudo sh get-docker.sh` lo esegue da amministratore: installa Docker e il plugin `compose`.
- `sudo usermod -aG docker $USER` aggiunge il tuo utente (`-aG`: in aggiunta agli altri gruppi) al gruppo `docker`, così i comandi `docker` non chiedono `sudo`.

Esci e rientra via SSH perché il gruppo nuovo valga, poi controlla con `docker compose version`.

## 2. Copiare il progetto

Dal tuo computer, nella cartella del progetto:

```
rsync -av --exclude '.venv' --exclude '.git' --exclude 'tests' --exclude 'docs' --exclude '__pycache__' --exclude '*.egg-info' --exclude 'local/chat.txt' --exclude 'web/node_modules' --exclude 'web/dist' --exclude 'data' ./ UTENTE@IP_PI:watchlog/
```

Cosa fa ogni parte:
- `rsync` copia solo ciò che è cambiato, quindi si rilancia così com'è per aggiornare il codice.
- `-a` conserva permessi e date, `-v` mostra i file copiati.
- Ogni `--exclude` salta un percorso. `local/chat.txt` è la chat esportata, che sul Pi non serve; `web/node_modules` e `web/dist` si ricreano nel build.
- `--exclude 'data'` tiene fuori il database: si copia una volta sola, al passo 3, perché poi quello del Pi è il riferimento e non va sovrascritto.
- `./` con la barra finale copia il contenuto della cartella corrente, non la cartella stessa.
- `UTENTE@IP_PI:watchlog/` è la destinazione: la cartella `watchlog` nella home dell'utente sul Pi, creata se manca.

I file `local/discord_token` e `local/tmdb_api_key` devono esistere prima dell'avvio: se ne manca uno, Docker crea al suo posto una cartella con quel nome e il bot non parte.

## 3. Copiare il database, una volta sola

Sul computer prima ferma tutto ciò che usa il database (`watchlog bot`, `watchlog api`): il database è in modalità WAL e le ultime scritture stanno in `data/watchlog.sqlite-wal` finché l'ultimo programma non lo chiude.
Quando in `data/` non c'è più `watchlog.sqlite-wal`:

```
rsync -av data/watchlog.sqlite UTENTE@IP_PI:watchlog/data/
```

Da qui in poi il database di riferimento è quello del Pi: le visioni scritte dal bot finiscono solo lì.

## 4. Costruire e avviare i container

Via SSH, sul Pi:

```
cd ~/watchlog
docker compose up -d --build
```

Cosa fa ogni parte:
- `docker compose` legge `docker-compose.yml` nella cartella corrente: i servizi sono `bot` e `api`.
- `up` crea e avvia i servizi.
- `-d` li lascia in esecuzione in background.
- `--build` costruisce l'immagine dai file della cartella prima di avviarli: compila la pagina web con Node e installa le dipendenze Python.

Il primo build sul Pi 3 scarica le immagini di base e le dipendenze e richiede diversi minuti; i successivi riusano quello che non è cambiato.

## 5. Verificare

```
docker compose ps
docker compose logs --tail 20 bot
```

- `ps` deve mostrare `watchlog-bot` e `watchlog-api` in stato `running`.
- `logs --tail 20 bot` mostra le ultime 20 righe del bot. Devi vedere:

```
discord.watchlog: Comandi sincronizzati sul server <ID del server>
discord.watchlog: Inserimento delle visioni attivo
discord.gateway: Shard ID None has connected to Gateway
```

Se invece legge "Inserimento delle visioni spento", manca `input_channel_id` in `config/discord.yaml`. Se all'avvio compare "Inserimento delle visioni disattivato", manca la chiave TMDB.

In Discord il bot risulta online: nel canale `#statistiche` prova `/stats`, nel canale delle visioni scrivi un film, per esempio `Heat (1995)`.
Da un dispositivo della rete locale apri `http://IP_PI:8000` (o `http://watchlog.local:8000`): è la pagina web, senza login, da usare solo in rete locale.

Importante: **per ogni token deve girare una sola istanza del bot**. Se lo hai provato sul computer con `watchlog bot`, fermalo prima di avviare quello sul Pi, altrimenti ogni comando riceve due risposte e Discord segnala un errore.

## Gestione quotidiana

| Cosa | Comando, da `~/watchlog` sul Pi |
|---|---|
| Vedere i log in diretta | `docker compose logs -f bot` (oppure `api` per la pagina) |
| Fermare tutto | `docker compose stop` |
| Riavviare | `docker compose restart` |
| Applicare modifiche a `config/users.yaml` | rilancia `rsync` (passo 2), poi `docker compose restart bot`: il bot riallinea gli utenti all'avvio |
| Aggiornare dopo modifiche al codice | rilancia `rsync` (passo 2), poi `docker compose up -d --build` |
| Spegnere e rimuovere i container | `docker compose down` |

I container ripartono da soli dopo un riavvio del Pi (`restart: unless-stopped`).

## Copie di sicurezza

La scheda SD si può guastare: conviene copiare spesso il database fuori dal Pi. Dal tuo computer:

```
ssh UTENTE@IP_PI 'cd ~/watchlog && docker compose stop && cp data/watchlog.sqlite backup.sqlite && docker compose start'
scp UTENTE@IP_PI:watchlog/backup.sqlite watchlog-$(date +%F).sqlite
```

Cosa fa ogni parte:
- `ssh UTENTE@IP_PI '...'` esegue i comandi tra apici sul Pi.
- `docker compose stop` ferma i container, così nel database ci sono tutte le scritture; `cp` ne fa una copia; `docker compose start` li riavvia. Bot e pagina restano fermi per pochi secondi.
- `scp ORIGINE DESTINAZIONE` copia la copia sul computer; `$(date +%F)` mette nel nome la data di oggi, per esempio `watchlog-2026-11-16.sqlite`.

## Problemi comuni

| Sintomo | Causa probabile |
|---|---|
| Il bot si ferma subito, nei log `File non trovato: config/discord.yaml` | Manca la cartella `config/` sul Pi, o `discord.yaml` al suo interno. |
| `Token Discord mancante` | `local/discord_token` non esiste, oppure è una cartella creata da Docker. Cancellala e copia il file. |
| `Token Discord non valido` | Il token è stato resettato o copiato male. Rigeneralo dal portale (Bot, Reset Token) e riscrivilo. |
| Il bot non reagisce ai messaggi nel canale delle visioni | Manca l'abilitazione «Message Content Intent» nel portale (scheda Bot), oppure `input_channel_id` non è quello del canale. |
| Il bot risponde "Non ti riconosco" | Il tuo `discord_id` non è in `config/users.yaml`: aggiungilo e riavvia il bot. |
| `/stats` non compare in Discord | Il bot non è nel server, oppure l'invito non aveva lo scope `applications.commands`. Rigenera il link di invito (vedi `docs/discord-app.md`). |
| `/stats` o la pagina dicono "Database non trovato" | Manca `data/watchlog.sqlite` sul Pi (passo 3). |
| `/stats` dice di usare un altro canale | Il comando funziona solo nel canale indicato in `stats_channel_id`. |
| La pagina non si apre | Controlla con `docker compose ps` che `watchlog-api` sia `running` e usa l'indirizzo del Pi con la porta `:8000`. |
| Il build si ferma con `exec format error` o pacchetti mancanti per `armhf` | Il sistema è a 32 bit: serve Raspberry Pi OS a 64 bit. |
