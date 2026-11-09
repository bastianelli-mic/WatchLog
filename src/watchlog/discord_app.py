"""Adattatore Discord: collega i comandi e l'inserimento delle visioni alla logica in `bot`, `live` ed `edits`. Non contiene logica propria."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from watchlog.bot import cancel_channel_error, stats_reply, user_names, viewings_reply
from watchlog.config import ConfigError, DiscordConfig
from watchlog.edits import Done, ViewingEditor
from watchlog.live import Ask, Cancelled, LiveService, Recorded, Rejected, Unrecognized

# Figlio del logger "discord": ne eredita il formato e il livello che discord.py imposta all'avvio.
log = logging.getLogger("discord.watchlog")

LOCAL_TZ = ZoneInfo("Europe/Rome")  # le date dei messaggi sono quelle del gruppo, non UTC
CHOICE_TIMEOUT_SECONDS = 180
PAGES_TIMEOUT_SECONDS = 300
PERIOD_CHOICES = [
    app_commands.Choice(name="Oggi", value="oggi"),
    app_commands.Choice(name="Questa settimana", value="settimana"),
    app_commands.Choice(name="Questo mese", value="mese"),
    app_commands.Choice(name="Quest'anno", value="anno"),
]


def run(
    token: str,
    config: DiscordConfig,
    db_path: Path,
    live: LiveService | None = None,
    editor: ViewingEditor | None = None,
) -> None:
    """Avvia il bot e resta in ascolto finché il processo non viene fermato."""
    try:
        _build_client(config, db_path, live, editor).run(token)
    except discord.LoginFailure as error:
        raise ConfigError("Token Discord non valido") from error
    except discord.PrivilegedIntentsRequired as error:
        raise ConfigError(
            "Attiva «Message Content Intent» nel portale Discord (scheda Bot) per leggere i messaggi delle visioni"
        ) from error


def _build_client(
    config: DiscordConfig, db_path: Path, live: LiveService | None, editor: ViewingEditor | None
) -> discord.Client:
    guild = discord.Object(id=config.guild_id)
    intents = discord.Intents.default()
    intents.message_content = live is not None  # privilegiato: serve solo per leggere le visioni scritte a mano

    class WatchLogClient(discord.Client):
        async def setup_hook(self) -> None:
            await tree.sync(guild=guild)
            log.info("Comandi sincronizzati sul server %s", config.guild_id)
            log.info("Inserimento delle visioni %s", "attivo" if live else "spento")

        async def on_message(self, message: discord.Message) -> None:
            if live is None or message.author.bot or message.channel.id != config.input_channel_id:
                return
            sent_at = message.created_at.astimezone(LOCAL_TZ).replace(tzinfo=None)
            outcome = await asyncio.to_thread(
                live.handle, str(message.author.id), message.content, sent_at, str(message.id)
            )
            await _apply(outcome, message, live)

    client = WatchLogClient(intents=intents)
    tree = app_commands.CommandTree(client)

    async def complete_user(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        names = [name for name in user_names(db_path) if current.lower() in name.lower()]
        return [app_commands.Choice(name=name, value=name) for name in names[:25]]

    @tree.command(name="stats", description="Statistiche dei film visti", guild=guild)
    @app_commands.describe(
        utente="Nome dell'utente; senza, il gruppo intero",
        periodo="Scorciatoia per il periodo; non si combina con dal e al",
        dal="Solo visioni da questa data (AAAA-MM-GG)",
        al="Solo visioni fino a questa data (AAAA-MM-GG)",
    )
    @app_commands.choices(periodo=PERIOD_CHOICES)
    async def stats(
        interaction: discord.Interaction,
        utente: str | None = None,
        periodo: app_commands.Choice[str] | None = None,
        dal: str | None = None,
        al: str | None = None,
    ) -> None:
        reply = stats_reply(
            db_path,
            config,
            interaction.channel_id,
            utente,
            dal,
            al,
            periodo=periodo.value if periodo else None,
            today=datetime.now(LOCAL_TZ).date(),
        )
        first, *others = reply.messages
        await interaction.response.send_message(first, ephemeral=reply.ephemeral)
        for message in others:
            await interaction.followup.send(message, ephemeral=reply.ephemeral)

    stats.autocomplete("utente")(complete_user)

    @tree.command(name="visioni", description="Elenco delle visioni registrate", guild=guild)
    @app_commands.describe(
        utente="Nome dell'utente; senza, il gruppo intero",
        periodo="Scorciatoia per il periodo; non si combina con dal e al",
        dal="Solo visioni da questa data (AAAA-MM-GG)",
        al="Solo visioni fino a questa data (AAAA-MM-GG)",
        titolo="Solo i film il cui titolo contiene questo testo",
    )
    @app_commands.choices(periodo=PERIOD_CHOICES)
    async def viewings(
        interaction: discord.Interaction,
        utente: str | None = None,
        periodo: app_commands.Choice[str] | None = None,
        dal: str | None = None,
        al: str | None = None,
        titolo: str | None = None,
    ) -> None:
        today = datetime.now(LOCAL_TZ).date()
        reply = viewings_reply(
            db_path, config, interaction.channel_id, utente, periodo.value if periodo else None, dal, al, titolo, today
        )
        if reply.ephemeral or len(reply.messages) == 1:
            await interaction.response.send_message(reply.messages[0], ephemeral=reply.ephemeral)
            return
        view = _PagesView(reply.messages, interaction.user.id)
        await interaction.response.send_message(reply.messages[0], view=view)
        view.message = await interaction.original_response()

    viewings.autocomplete("utente")(complete_user)

    if editor is not None:

        @tree.command(name="annulla", description="Annulla una visione: il numero compare in /visioni", guild=guild)
        @app_commands.describe(numero="Numero della visione, come compare in /visioni")
        async def cancel(interaction: discord.Interaction, numero: app_commands.Range[int, 1]) -> None:
            problem = cancel_channel_error(config, interaction.channel_id)
            if problem:
                await interaction.response.send_message(problem, ephemeral=True)
                return
            outcome = await asyncio.to_thread(editor.request_cancel, str(interaction.user.id), numero)
            if not isinstance(outcome, Ask):
                await interaction.response.send_message(outcome.text, ephemeral=True)
                return
            # La domanda la vede solo chi ha dato il comando; l'esito, se confermato, lo vede tutto il canale.
            view = _ChoiceView(outcome, interaction.user.id, editor.answer, _cancel_presenter(interaction.channel))
            await interaction.response.send_message(outcome.text, view=view, ephemeral=True)
            view.message = await interaction.original_response()

        @tree.command(name="voto", description="Dai un voto a una visione (di default l'ultima che hai registrato)", guild=guild)
        @app_commands.describe(
            voto="Da 0,5 a 5, a passi di 0,5",
            numero="Numero della visione, come compare in /visioni (se manca, la tua ultima)",
        )
        async def rate(
            interaction: discord.Interaction,
            voto: app_commands.Range[float, 0.5, 5.0],
            numero: app_commands.Range[int, 1] | None = None,
        ) -> None:
            problem = cancel_channel_error(config, interaction.channel_id)
            if problem:
                await interaction.response.send_message(problem, ephemeral=True)
                return
            outcome = await asyncio.to_thread(editor.set_rating, str(interaction.user.id), voto, numero)
            await interaction.response.send_message(outcome.text, ephemeral=True)
            if isinstance(outcome, Done):
                await interaction.channel.send(outcome.announcement)

    return client


async def _apply(
    outcome, original: discord.Message, live: LiveService, bot_message: discord.Message | None = None
) -> None:
    """Mostra l'esito: reazione sul messaggio dell'utente e risposta del bot (nuova, o modificata se già c'è)."""

    async def say(text: str, view: discord.ui.View | None = None) -> discord.Message:
        if bot_message is None:
            return await original.reply(text, view=view, mention_author=False)
        await bot_message.edit(content=text, view=view)
        return bot_message

    if isinstance(outcome, Ask):
        view = _ChoiceView(
            outcome,
            original.author.id,
            live.answer,
            lambda next_outcome, interaction: _apply(next_outcome, original, live, interaction.message),
        )
        view.message = await say(outcome.text, view)
    elif isinstance(outcome, Recorded):
        await original.add_reaction("✅")
        await say(outcome.text)
    elif isinstance(outcome, Rejected):
        await original.add_reaction("❌")
        await say(outcome.text)
    elif isinstance(outcome, Cancelled):
        await say(outcome.text)
    elif isinstance(outcome, Unrecognized):
        await original.add_reaction("❓")


def _cancel_presenter(channel):
    """Chiude la domanda di annullamento (messaggio privato) e, se fatto, lo annuncia nel canale."""

    async def present(outcome, interaction: discord.Interaction) -> None:
        await interaction.edit_original_response(content=outcome.text, view=None)
        if isinstance(outcome, Done):
            await channel.send(outcome.announcement)

    return present


class _PagesView(discord.ui.View):
    """Bottoni per scorrere le pagine dell'elenco: li usa solo chi ha lanciato il comando."""

    def __init__(self, pages: list[str], owner_id: int):
        super().__init__(timeout=PAGES_TIMEOUT_SECONDS)
        self._pages, self._owner_id, self._index = pages, owner_id, 0
        self.message: discord.Message | None = None
        self._previous = discord.ui.Button(label="◀ Precedente", style=discord.ButtonStyle.secondary, disabled=True)
        self._next = discord.ui.Button(label="Successivo ▶", style=discord.ButtonStyle.primary)
        self._previous.callback = self._go(-1)
        self._next.callback = self._go(+1)
        self.add_item(self._previous)
        self.add_item(self._next)

    def _go(self, step: int):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self._owner_id:
                await interaction.response.send_message(
                    "Può scorrere l'elenco solo chi ha lanciato il comando.", ephemeral=True
                )
                return
            self._index += step
            self._previous.disabled = self._index == 0
            self._next.disabled = self._index == len(self._pages) - 1
            await interaction.response.edit_message(content=self._pages[self._index], view=self)

        return callback

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(view=None)


class _ChoiceView(discord.ui.View):
    """Bottoni di scelta: risponde solo chi ha fatto la richiesta, e per un tempo limitato.

    `answer` trasforma la scelta in un esito; `present` lo mostra, a partire dall'interazione del bottone.
    """

    def __init__(self, ask: Ask, owner_id: int, answer, present):
        super().__init__(timeout=CHOICE_TIMEOUT_SECONDS)
        self._ask, self._owner_id, self._answer, self._present = ask, owner_id, answer, present
        self.message: discord.Message | None = None
        for option in ask.options:
            style = discord.ButtonStyle.secondary if option.value in ("none", "no") else discord.ButtonStyle.primary
            button = discord.ui.Button(label=option.label[:80], style=style)
            button.callback = self._callback_for(option.value)
            self.add_item(button)

    def _callback_for(self, value: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self._owner_id:
                await interaction.response.send_message(
                    "Può scegliere solo chi ha scritto il messaggio.", ephemeral=True
                )
                return
            await interaction.response.defer()
            self.stop()
            outcome = await asyncio.to_thread(self._answer, self._ask, value)
            await self._present(outcome, interaction)

        return callback

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(content="Tempo scaduto: non ho cambiato nulla.", view=None)
