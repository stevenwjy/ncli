"""ncli: A note-taking command-line interface (CLI) using Click.

This module provides the main CLI for managing notes using Audible, Kindle, and Notion services.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union, get_type_hints

import click
import toml
from click import echo, prompt
from pydantic import BaseModel  # pylint: disable=no-name-in-module

from ncli import constants, \
    kit_amazon as amazon, \
    kit_audible as audible, \
    kit_kindle as kindle, \
    kit_notion as notion, \
    kit_youtube as youtube, \
    utils
from ncli.kit_amazon import Config as AmazonConfig
from ncli.kit_youtube import Config as YoutubeConfig


class Config(BaseModel):
    """
    General config for the CLI
    """
    audible_export_dir: str = ""
    kindle_export_dir: str = ""
    notion_export_dir: str = ""

    amazon: AmazonConfig = AmazonConfig()

    youtube: YoutubeConfig = YoutubeConfig()


# TODO: add support to customize config file location
CONFIG_PATH = constants.BASE_PATH.joinpath('config.toml')


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Note-taking CLI."""
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)

    # Load config file if exists
    config_dict = {}
    config_path = CONFIG_PATH
    if config_path.exists() and config_path.is_file():
        config_dict = toml.load(config_path)
    ctx.obj['config'] = Config.parse_obj(config_dict)


# ---
# Config
# ---


@cli.group(name='config')
@click.pass_context
def config_cli(_: click.Context) -> None:
    """Group command to set up basic config"""


@config_cli.command(name='list')
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """
    Command to list the config values.
    """
    config: Config = ctx.obj['config']

    echo('Config:')
    kv_pairs = _config_to_kv(config)
    for pair in kv_pairs:
        echo(f'{pair[0]} = {pair[1]}')


def _config_to_kv(config: BaseModel, prefix: str = '') -> list:
    kv_pairs = []

    for field in config.__fields__.keys():
        value = getattr(config, field)
        key = f'{prefix}.{field}' if prefix else field

        if isinstance(value, BaseModel):
            kv_pairs.extend(_config_to_kv(value, key))
        else:
            kv_pairs.append((key, value))

    return kv_pairs


@config_cli.command(name='set')
@click.argument('key', type=str)
@click.argument('value', type=str)
@click.pass_context
def config_set(
    ctx: click.Context,
    key: str,
    value: str,  # note that the string can be converted to int or float later if necessary
) -> None:
    """
    Command to set the value of a specific config key.
    """
    config: Config = ctx.obj['config']
    _update_config(config, key, value)
    _save_config(config)


def _update_config(config: BaseModel, key: str, value: Union[str, int]) -> None:
    keys = key.split('.', 1)

    if len(keys) > 1:
        sub_config = getattr(config, keys[0])
        _update_config(sub_config, keys[1], value)
    else:
        # Get declared type of the field
        declared_type = get_type_hints(config.__class__)[keys[0]]

        # Convert string to declared type if necessary
        if declared_type is int or declared_type is float:
            try:
                value = declared_type(value)
            except ValueError as e:
                raise TypeError(
                    f'Cannot convert value to {declared_type}') from e

        # Check if the value has correct type
        if not isinstance(value, declared_type):
            raise TypeError(
                f'Expected type {declared_type} for field {keys[0]}, got {type(value)}')

        setattr(config, keys[0], value)


def _to_dict_without_default(model: BaseModel) -> Dict[str, Any]:
    return {
        k: _to_dict_without_default(v) if isinstance(v, BaseModel) else v
        for k, v in model.__dict__.items()
        if v != model.__fields__[k].default
    }


def _save_config(config: Config):
    config_str = utils.toml_dumps_with_newline(
        _to_dict_without_default(config))

    # Create directory for first time use
    if not constants.BASE_PATH.exists():
        os.makedirs(constants.BASE_PATH, exist_ok=True)

    with open(CONFIG_PATH, "w", encoding='utf-8') as file:
        file.write(config_str)


@config_cli.command(name='amazon-auth')
@click.pass_context
def config_amazon_auth(ctx: click.Context) -> None:
    """
    Command to set up amazon auth.
    """
    config: Config = ctx.obj['config']
    if config.amazon.auth_file:
        if not utils.prompt_user(
            f'Auth file {config.amazon.auth_file} is found in the config. '
            'Do you want to replace it?'
        ):
            # If the user answer no, terminate the command
            return

    auth_file = None
    while auth_file is None:
        auth_file = prompt(
            'Please enter a name for the auth file',
            default='auth' + '.' + amazon.DEFAULT_AUTH_FILE_EXTENSION,
        )
        if (constants.BASE_PATH / auth_file).exists():
            echo()
            if not utils.prompt_user('File with the given name already exists. Do you want to overwrite?'):
                auth_file = None  # This will repeat the loop
                continue
        # Else will exit the for loop

    encryption_pass = None
    if utils.prompt_user('Do you want to encrypt the auth file?'):
        echo()
        encryption_pass = prompt('Please enter a password for the encryption',
                                 confirmation_prompt=True, hide_input=True)

    country_code = prompt(
        'Please enter your country code',
        show_choices=True,
        type=click.Choice(amazon.AVAILABLE_COUNTRY_CODES)
    )

    # Recommended to log in with external browser.
    # Safer and can avoid the need to enter OTP, Captcha, etc. on terminal.
    external_login = utils.prompt_user(
        'Do you want to login with external browser (recommended)?'
    )

    username = None
    password = None
    if not external_login:
        username = prompt('Please enter your Amazon username')
        password = prompt('Please enter your Amazon password',
                          confirmation_prompt=True, hide_input=True)

    # We currently do not support pre-Amazon Audible account (i.e., by using `with_username` = False).
    # Probably need to do some refactoring to support multiple profiles first before we can do that.
    amazon.build_auth_file(
        filename=constants.BASE_PATH/auth_file,
        username=username,
        password=password,
        country_code=country_code,
        file_password=encryption_pass,
        external_login=external_login,
        with_username=False,
    )

    config.amazon.auth_file = auth_file
    config.amazon.country_code = country_code
    _save_config(config)


# ---
# Audible
# ---


@cli.group(name='audible')
@click.pass_context
def audible_cli(_: click.Context) -> None:
    """Audible group command."""


@audible_cli.command(name='export')
@click.option('--target', type=click.Path(), help='Path to the target location for the export.')
@click.option('--renew', is_flag=True, help='Fetch all books regardless of the index data.')
@click.pass_context
def audible_export(
    ctx: click.Context,
    target: Optional[str],
    renew: bool,
) -> None:
    """Audible export command."""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.audible_export_dir
    if target is None:
        raise ValueError('unknown export target')

    audible.export(config.amazon, Path(target).expanduser(), renew)


# ---
# Kindle
# ---


@cli.group(name='kindle')
@click.pass_context
def kindle_cli(_: click.Context) -> None:
    """Kindle group command."""


@kindle_cli.command(name='export')
@click.option('--target', type=click.Path(), help='Path to the target location for the export.')
@click.option('--renew', is_flag=True, help='Fetch all books regardless of the index data.')
@click.pass_context
def kindle_export(
    ctx: click.Context,
    target: Optional[str],
    renew: bool,
) -> None:
    """Kindle export command."""
    config: Config = ctx.obj['config']
    target = target if target is not None else config.kindle_export_dir
    if target is None:
        raise ValueError('unknown export target')

    kindle.export(config.amazon, Path(target).expanduser(), renew)


# ---
# Notion
# ---


@cli.group(name='notion')
@click.pass_context
def notion_cli(_: click.Context) -> None:
    """Notion group command."""


@notion_cli.command(name='export')
@click.option('--source', type=click.Path(), help='Path to the source file.')
@click.option('--target', type=click.Path(), help='Path to the target location after the conversion.')
@click.option('--force', is_flag=True, help='Removes the current target directory if it exists.')
@click.pass_context
def notion_export(
    ctx: click.Context,
    source: str,
    target: Optional[str],
    force: bool,
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
    )


# ---
# YouTube
# ---


@cli.group(name='youtube')
@click.pass_context
def youtube_cli(_: click.Context) -> None:
    """YouTube group command."""


@youtube_cli.command(name='export')
@click.option('--source', type=str, help='URL to the YouTube video')
@click.option('--target', type=click.Path(), help='Path to the target export directory')
@click.option('--transcribe', is_flag=True, help='Prints the video transcript')
@click.option('--summarize', is_flag=True, help='Summarizes the video transcript')
@click.pass_context
def youtube_export(
    ctx: click.Context,
    source: str,
    target: Optional[str],
    transcribe: bool,
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
        transcribe,
        summarize,
        config.youtube,
    )
