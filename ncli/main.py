from dotenv import load_dotenv

from ncli.cli import cli


def main():
    load_dotenv(".env")

    # pylint: disable=no-value-for-parameter
    cli(obj={})
