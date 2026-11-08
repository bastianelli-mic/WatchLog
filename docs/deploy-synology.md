# Installare il bot sul Synology

Guida passo per passo per far girare il bot Discord in un container sul Synology, con riavvio automatico.
Il container è costruito sul NAS stesso, quindi l'architettura (ARM sul DS223) non richiede nulla di speciale.
Le voci dei menu di DSM vengono dalla versione 7.4 come la conosciamo: se qualcosa è spostato, cerca la voce equivalente.
La build per ARM non è stata provata: il primo avvio sul NAS è la verifica.

## Cosa serve

- DSM 7.4 con **Container Manager** installato (Centro pacchetti).
- Accesso SSH al NAS: Pannello di controllo, Terminale e SNMP, **Abilita servizio SSH**.
- L'app Discord già creata, con il token in `local/discord_token` (vedi `docs/discord-app.md`).
- `config/discord.yaml` e `config/users.yaml` compilati, e il database `data/watchlog.sqlite` già importato.

## 1. Preparare la cartella sul NAS

Scegli una cartella condivisa, per esempio `/volume1/docker/watchlog`, e creala dal NAS con File Station oppure via SSH.

## 2. Copiare il progetto sul NAS

Dal tuo computer, nella cartella del progetto:

```
rsync -av --exclude '.venv' --exclude '.git' --exclude 'tests' --exclude 'docs' --exclude '__pycache__' --exclude '*.egg-info' --exclude 'local/chat.txt' --exclude 'local/tmdb_api_key' ./ NOME_UTENTE@IP_NAS:/volume1/docker/watchlog/
```

Cosa fa ogni parte:
- `rsync` copia solo ciò che è cambiato, quindi si può rilanciare per aggiornare.
- `-a` conserva permessi e date, `-v` mostra i file copiati.
- Ogni `--exclude` salta un percorso. Le ultime due righe tengono fuori dal NAS la chat esportata e la chiave TMDB, che il bot non usa.
- `./` con la barra finale copia il contenuto della cartella corrente, non la cartella stessa.
- `NOME_UTENTE@IP_NAS:/volume1/docker/watchlog/` è l'utente SSH del NAS, il suo indirizzo e la cartella di destinazione.

Dopo la copia, sul NAS devono esserci almeno: `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `src/`, `data/watchlog.sqlite`, `config/discord.yaml`, `config/users.yaml` e `local/discord_token`.
Se non hai rsync, puoi caricare gli stessi file con File Station o con `scp`.

Il file `local/discord_token` deve esistere prima dell'avvio: se manca, Docker crea al suo posto una cartella con quel nome e il bot non parte.

## 3. Costruire e avviare il container

Via SSH, sul NAS:

```
cd /volume1/docker/watchlog
sudo docker compose up -d --build
```

Cosa fa ogni parte:
- `docker compose` legge `docker-compose.yml` nella cartella corrente. Se il tuo DSM ha solo la versione vecchia, il comando è `docker-compose` con il trattino.
- `up` crea e avvia il servizio.
- `-d` lo lascia in esecuzione in background.
- `--build` costruisce l'immagine dai file della cartella, prima di avviarlo.

In alternativa, da Container Manager: **Progetto**, **Crea**, scegli la cartella e indica di usare il `docker-compose.yml` esistente.
Il primo avvio scarica l'immagine di base e le dipendenze Python, e può richiedere qualche minuto.

## 4. Verificare

```
sudo docker logs --tail 20 watchlog
```

Devi vedere queste due righe:

```
discord.watchlog: Comandi sincronizzati sul server <ID del server>
discord.gateway: Shard ID None has connected to Gateway
```

Poi, in Discord, il bot risulta online. Nel canale `#statistiche` scrivi `/stats` e premi invio.

Importante: **per ogni token deve girare una sola istanza del bot**. Se lo hai provato sul computer con `watchlog bot`, fermalo prima di usare quello sul NAS, altrimenti ogni comando riceve due risposte e Discord segnala un errore.

## Gestione quotidiana

| Cosa | Comando, dalla cartella del progetto sul NAS |
|---|---|
| Vedere i log in diretta | `sudo docker logs -f watchlog` |
| Fermare il bot | `sudo docker compose stop` |
| Riavviarlo | `sudo docker compose restart` |
| Applicare modifiche a `config/users.yaml` | rilancia `rsync` (passo 2), poi `sudo docker compose restart` |
| Aggiornare dopo modifiche al codice | rilancia `rsync` (passo 2), poi `sudo docker compose up -d --build` |
| Spegnere e rimuovere il container | `sudo docker compose down` |

Il container si riavvia da solo dopo un riavvio del NAS (`restart: unless-stopped`).

## Aggiornare il database

Per ora il database si crea sul computer con `watchlog import` e si copia sul NAS.
Per sostituirlo, ferma il bot, copia il nuovo `data/watchlog.sqlite` con `rsync` o File Station e riavvialo.

Quando il bot inizierà a inserire visioni (inserimento live), il database sul NAS diventerà quello di riferimento: da quel momento non va più sovrascritto con una copia dal computer, o si perdono le visioni inserite dal bot.

## Problemi comuni

| Sintomo | Causa probabile |
|---|---|
| Il container si ferma subito, nei log `File non trovato: config/discord.yaml` | Manca la cartella `config/` sul NAS, o `discord.yaml` al suo interno. |
| `Token Discord mancante` | `local/discord_token` non esiste, oppure è una cartella creata da Docker. Cancellala e copia il file. |
| `Token Discord non valido` | Il token è stato resettato o copiato male. Rigeneralo dal portale (Bot, Reset Token) e riscrivilo. |
| `/stats` non compare in Discord | Il bot non è nel server, oppure l'invito non aveva lo scope `applications.commands`. Rigenera il link di invito (vedi `docs/discord-app.md`). |
| `/stats` risponde "Database non trovato" | Manca `data/watchlog.sqlite` sul NAS. |
| `/stats` dice di usare un altro canale | Il comando funziona solo nel canale indicato in `stats_channel_id`. |
