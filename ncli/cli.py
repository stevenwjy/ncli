"""ncli: A note-taking command-line interface (CLI) using Click.

This module provides the main CLI for managing notes using Audible, Kindle, and Notion services.
"""

from pathlib import Path
from typing import Optional

import click
import toml
from pydantic import BaseModel  # pylint: disable=no-name-in-module

from ncli import constants, \
    kit_amazon as amazon, \
    kit_audible as audible, \
    kit_kindle as kindle, \
    kit_notion as notion, \
    kit_youtube as youtube


class Config(BaseModel):
    """
    General config for the CLI
    """
    audible_export_dir: str = ""
    kindle_export_dir: str = ""
    notion_export_dir: str = ""

    amazon: amazon.Config

    youtube: youtube.Config


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Note-taking CLI."""
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)

    # Load config file if exists
    config_dict = {}
    config_path = constants.BASE_PATH.joinpath('config.toml')
    if config_path.exists() and config_path.is_file():
        config_dict = toml.load(config_path)
    ctx.obj['config'] = Config(**config_dict)


@cli.group(name='audible')
@click.pass_context
def audible_cli(_: click.Context) -> None:
    """Audible group command."""


@audible_cli.command(name='export')
@click.option('--target', type=click.Path(), help='Path to the target location for the export.')
@click.pass_context
def audible_export(
    ctx: click.Context,
    target: Optional[str],
) -> None:
    """Audible export command."""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.audible_export_dir
    if target is None:
        raise ValueError('unknown export target')

    audible.export(config.amazon, Path(target).expanduser())


@cli.group(name='kindle')
@click.pass_context
def kindle_cli(_: click.Context) -> None:
    """Kindle group command."""


@kindle_cli.command(name='export')
@click.option('--target', type=click.Path(), help='Path to the target location for the export.')
@click.option('--skip-check', is_flag=True, help='Always re-export all books.')
@click.pass_context
def kindle_export(
    ctx: click.Context,
    target: Optional[str],
    skip_check: bool,
) -> None:
    """Kindle export command."""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.kindle_export_dir
    if target is None:
        raise ValueError('unknown export target')

    kindle.export(config.amazon, Path(target).expanduser(), skip_check)


@cli.group(name='notion')
@click.pass_context
def notion_cli(_: click.Context) -> None:
    """Notion group command."""


@notion_cli.command(name='export')
@click.option('--source', type=click.Path(), help='Path to the source file.')
@click.option('--target', type=click.Path(), help='Path to the target location after the conversion.')
@click.option('--force', is_flag=True, help='Removes the current target directory if it exists.')
@click.option('--clean', is_flag=True, help='Removes the source directory when the export operation finishes.')
@click.pass_context
def notion_export(
    ctx: click.Context,
    source: str,
    target: Optional[str],
    force: bool,
    clean: bool,
) -> None:
    """Notion export command."""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.notion_export_dir
    if target is None:
        raise ValueError('unknown export target')

    notion.export(
        Path(source).expanduser(),
        Path(target).expanduser(),
        force,
        clean,
    )


@cli.group(name='youtube')
@click.pass_context
def youtube_cli(_: click.Context) -> None:
    """YouTube group command."""


@youtube_cli.command(name='export')
@click.option('--source', type=str, help='URL to the YouTube video')
@click.option('--target', type=click.Path(), help='Path to the target export directory')
@click.option('--summarize', is_flag=True, help='Summarizes the video transcript')
@click.pass_context
def youtube_export(
    ctx: click.Context,
    source: str,
    target: Optional[str],
    summarize: bool,
):
    """Export YouTube video data"""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.youtube.export_dir
    if target is None:
        raise ValueError('unknown export target')

    youtube.export(
        source,
        Path(target).expanduser(),
        summarize,
        config.youtube,
    )
