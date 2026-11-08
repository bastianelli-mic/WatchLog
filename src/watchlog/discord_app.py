"""Adattatore Discord: collega /stats e l'inserimento delle visioni alla logica in `bot` e `live`. Non contiene logica propria."""

import asyncio
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from watchlog.bot import stats_reply, user_names
from watchlog.config import ConfigError, DiscordConfig
from watchlog.live import Ask, Cancelled, LiveService, Recorded, Rejected, Unrecognized

# Figlio del logger "discord": ne eredita il formato e il livello che discord.py imposta all'avvio.
log = logging.getLogger("discord.watchlog")

LOCAL_TZ = ZoneInfo("Europe/Rome")  # le date dei messaggi sono quelle del gruppo, non UTC
CHOICE_TIMEOUT_SECONDS = 180


def run(token: str, config: DiscordConfig, db_path: Path, live: LiveService | None = None) -> None:
    """Avvia il bot e resta in ascolto finché il processo non viene fermato."""
    try:
        _build_client(config, db_path, live).run(token)
    except discord.LoginFailure as error:
        raise ConfigError("Token Discord non valido") from error
    except discord.PrivilegedIntentsRequired as error:
        raise ConfigError(
            "Attiva «Message Content Intent» nel portale Discord (scheda Bot) per leggere i messaggi delle visioni"
        ) from error


def _build_client(config: DiscordConfig, db_path: Path, live: LiveService | None) -> discord.Client:
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

    @tree.command(name="stats", description="Statistiche dei film visti", guild=guild)
    @app_commands.describe(
        utente="Nome dell'utente; senza, il gruppo intero",
        dal="Solo visioni da questa data (AAAA-MM-GG)",
        al="Solo visioni fino a questa data (AAAA-MM-GG)",
    )
    async def stats(
        interaction: discord.Interaction,
        utente: str | None = None,
        dal: str | None = None,
        al: str | None = None,
    ) -> None:
        reply = stats_reply(db_path, config, interaction.channel_id, utente, dal, al)
        first, *others = reply.messages
        await interaction.response.send_message(first, ephemeral=reply.ephemeral)
        for message in others:
            await interaction.followup.send(message, ephemeral=reply.ephemeral)

    @stats.autocomplete("utente")
    async def complete_user(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        names = [name for name in user_names(db_path) if current.lower() in name.lower()]
        return [app_commands.Choice(name=name, value=name) for name in names[:25]]

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
        view = _ChoiceView(live, outcome, original)
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


class _ChoiceView(discord.ui.View):
    """Bottoni di scelta: risponde solo l'autore del messaggio, e per un tempo limitato."""

    def __init__(self, live: LiveService, ask: Ask, original: discord.Message):
        super().__init__(timeout=CHOICE_TIMEOUT_SECONDS)
        self._live, self._ask, self._original = live, ask, original
        self.message: discord.Message | None = None
        for option in ask.options:
            style = discord.ButtonStyle.secondary if option.value in ("none", "no") else discord.ButtonStyle.primary
            button = discord.ui.Button(label=option.label[:80], style=style)
            button.callback = self._callback_for(option.value)
            self.add_item(button)

    def _callback_for(self, value: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self._original.author.id:
                await interaction.response.send_message(
                    "Può scegliere solo chi ha scritto il messaggio.", ephemeral=True
                )
                return
            await interaction.response.defer()
            self.stop()
            outcome = await asyncio.to_thread(self._live.answer, self._ask, value)
            await _apply(outcome, self._original, self._live, bot_message=interaction.message)

        return callback

    async def on_timeout(self) -> None:
        if self.message is not None:
            await self.message.edit(content="Tempo scaduto: non ho registrato nulla.", view=None)
