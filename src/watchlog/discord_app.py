"""Adattatore Discord: collega il comando /stats alla logica in `bot`. Non contiene logica propria."""

import logging
from pathlib import Path

import discord
from discord import app_commands

from watchlog.bot import stats_reply, user_names
from watchlog.config import ConfigError, DiscordConfig

# Figlio del logger "discord": ne eredita il formato e il livello che discord.py imposta all'avvio.
log = logging.getLogger("discord.watchlog")


def run(token: str, config: DiscordConfig, db_path: Path) -> None:
    """Avvia il bot e resta in ascolto finché il processo non viene fermato."""
    try:
        _build_client(config, db_path).run(token)
    except discord.LoginFailure as error:
        raise ConfigError("Token Discord non valido") from error


def _build_client(config: DiscordConfig, db_path: Path) -> discord.Client:
    guild = discord.Object(id=config.guild_id)

    class WatchLogClient(discord.Client):
        async def setup_hook(self) -> None:
            await tree.sync(guild=guild)
            log.info("Comandi sincronizzati sul server %s", config.guild_id)

    client = WatchLogClient(intents=discord.Intents.default())  # nessun intent privilegiato: bastano i comandi
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
