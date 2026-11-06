# Creare l'app Discord di WatchLog

Guida passo per passo per creare l'applicazione e il bot Discord, prendere il token, invitare il bot nel server e raccogliere gli ID che servono alla configurazione.
I nomi delle voci vengono dal portale Discord come lo conoscevamo al momento della scrittura: se qualcosa è spostato o rinominato, cerca la voce equivalente.
Conviene fare le prove su un server di test, e invitare il bot nel server degli amici solo quando funziona.

## 1. Creare l'applicazione

1. Vai su discord.com/developers/applications ed entra con il tuo account.
2. Premi **New Application** in alto a destra.
3. Come nome scrivi per esempio `WatchLog` (è anche il nome che vedranno gli amici), accetta i termini e premi **Create**.

## 2. Creare il bot e prendere il token

1. Nel menu a sinistra apri **Bot**.
2. Premi **Reset Token** e conferma. Il token compare una volta sola: copialo subito.
3. Disattiva **Public Bot**, così nessun altro può invitare il bot nei suoi server.
4. Più sotto, in **Privileged Gateway Intents**, attiva **Message Content Intent**. Serve per leggere i messaggi `data - titolo (anno)` scritti a mano nel canale delle visioni. Per i soli comandi `/stats` non serve, ma attivarlo ora evita di tornare qui. Sotto i 100 server non servono verifiche.

## 3. Salvare il token senza esporlo

Il token non va incollato in chat, né scritto in un file versionato.
In un terminale, dalla cartella del progetto:

```
mkdir -p local && umask 077 && read -rs t && printf '%s' "$t" > local/discord_token && unset t
```

Cosa fa ogni parte:
- `mkdir -p local` crea la cartella, che git ignora.
- `umask 077` rende il file leggibile solo da te.
- `read -rs t` aspetta che tu incolli il token e premi invio. `-s` non lo mostra a schermo, `-r` evita che i backslash vengano interpretati.
- `printf '%s' "$t" > local/discord_token` lo scrive nel file senza andare a capo.
- `unset t` toglie il token dalla memoria della shell.

Se il token finisce per sbaglio dove non deve, torna su **Bot** e premi di nuovo **Reset Token**: il vecchio smette di funzionare.

## 4. Generare il link di invito

1. Nel menu a sinistra apri **OAuth2**, poi **URL Generator**.
2. In **Scopes** spunta `bot` e `applications.commands`. Il secondo serve ai comandi `/stats`.
3. Sotto compare **Bot Permissions**. Spunta soltanto:
   - View Channels
   - Send Messages
   - Read Message History
   - Add Reactions
   - Use Application Commands
4. In fondo c'è il **Generated URL**: copialo.

## 5. Invitare il bot nel server

1. Apri il link nel browser, scegli il server (serve il permesso **Gestisci server**) e premi **Autorizza**.
2. Il bot compare nell'elenco dei membri, offline: è normale, diventa online solo quando il programma gira.

## 6. Preparare i canali

Nel server crea due canali di testo:
- `#film-visti`, dove si scrivono le visioni.
- `#statistiche`, dove si lanciano i comandi e il bot risponde.

Se li rendi privati, aggiungi esplicitamente il bot tra i membri autorizzati di ciascuno, altrimenti non li vede.

## 7. Raccogliere gli ID

1. In Discord apri **Impostazioni utente**, poi **Avanzate**, e attiva **Modalità sviluppatore**.
2. Fai clic destro sul server e scegli **Copia ID server**.
3. Fai clic destro su ciascuno dei due canali e scegli **Copia ID canale**.
4. Per ogni amico già iscritto, fai clic destro sul suo nome e scegli **Copia ID utente**: va nel campo `discord_id` di `config/users.yaml`.

Gli ID di server, canali e utenti non sono segreti. Il token sì, sempre.

## Cosa serve alla configurazione

- Il token in `local/discord_token`. Per controllare che il file esista senza mostrarne il contenuto: `ls -l local/discord_token`.
- L'ID del server e quelli dei due canali.
- Gli eventuali `discord_id` degli amici già iscritti, da mettere in `config/users.yaml`.
