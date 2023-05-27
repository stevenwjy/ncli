"""
A module for processing and managing Amazon data.
"""
from __future__ import annotations

import io
import getpass
import os.path

from typing import List, Optional, Union
from datetime import datetime
from pathlib import Path

import click
import httpx
import requests
import toml
from PIL import Image
from pydantic import BaseModel, Field  # pylint: disable=no-name-in-module
from click import echo, secho, prompt

from audible import Authenticator
from audible.auth import detect_file_encryption
from audible.login import default_login_url_callback

from ncli import constants
from ncli.utils import prompt_user, format_duration_from_ms, toml_dumps_with_newline

AVAILABLE_COUNTRY_CODES: List[str] = [
    "us", "ca", "uk", "au", "fr", "de", "es", "jp", "it", "in"]
DEFAULT_AUTH_FILE_EXTENSION: str = "json"
DEFAULT_AUTH_FILE_ENCRYPTION: str = "json"


class Config(BaseModel):
    """
    Config for Amazon products.
    """
    auth_file: str = ''
    country_code: str = 'us'


def load_authenticator(config: Config) -> Authenticator:
    """
    Loads authenticator
    """
    if config.auth_file:
        file_path = constants.BASE_PATH.joinpath(config.auth_file)
        pwd = None
        if detect_file_encryption(file_path):
            pwd = getpass.getpass('Enter auth file password: ')

        return Authenticator.from_file(file_path, pwd)

    raise ValueError('config without auth file not supported')


class Book(BaseModel):
    """
    Represents a book with metadata.
    """
    asin: str = ''
    title: str = ''
    subtitle: Optional[str] = None

    # Author of the book.
    #
    # For a book that has more than one authors, we concatenate their names (comma-separated) into
    # a single string here for simplicity.
    author: str = ''

    # URL for the book cover image
    image_url: str = ''
    # URL for the accompanying PDF (only for Audible).
    # Note that the URL may require some cookies to be accessed.
    pdf_url: Optional[str] = None

    # Publication date for the book. Currently only available for Audible.
    publication_date: Optional[str] = None
    # Purchase date for the book. Currently only available for Audible.
    purchase_date: Optional[str] = None

    # Last opened date represents:
    # - Last time the book is read for Kindle.
    # - Last time the book is listened for Audible (based on last update time for the last listened position).
    last_opened_date: str = ''


class Chapter(BaseModel):
    """
    Represents a chapter from a book.
    """
    title: str = ''

    # For Audible
    #
    # The clip start and end values are in milisecond offset w.r.t. the beginning time.
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

    subchapters: Optional[List[Chapter]] = None


class Annotation(BaseModel):
    """
    Represents a single annotation (highlight and/or note) from a book.
    """
    # For Kindle
    highlight: Optional[str] = None
    highlight_color: Optional[str] = None

    # For Kindle and Audible
    note: Optional[str] = None

    # For Kindle
    #
    # Note that location is guaranteed to exist for Kindle.
    location: Optional[int] = None
    page: Optional[int] = None

    # For Audible
    #
    # The clip start and end values are in milisecond offset w.r.t. the beginning time.
    clip_start_ms: Optional[int] = None
    clip_end_ms: Optional[int] = None

    # Currently only available for Audible
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ExportItem(BaseModel):
    """
    Represents an item to be exported, containing a Book and its associated metadata.
    """
    last_updated_time: str
    info: Book

    checked: bool = Field(default=False, exclude=True)

    class Config:  # pylint: disable=too-few-public-methods
        """
        Config for the pydantic dataclass
        """
        fields = {'checked': {'exclude': True}}


class ExportIndex(BaseModel):
    """
    Represents an index of exported items.
    """
    books: List[ExportItem]

    @staticmethod
    def load_or_default(path: Path):
        """
        Load the export index or default to an empty state if there is no such file.
        """
        if not os.path.exists(path):
            return ExportIndex(books=[])

        with open(path, "r", encoding='utf-8') as file:
            index_str = file.read()
        index = toml.loads(index_str)
        return ExportIndex(**index)

    def save(self, path: Path):
        """
        Save the export index into the specified path.
        """
        index_str = toml_dumps_with_newline(self.dict())
        with open(path, "w", encoding='utf-8') as file:
            file.write(index_str)

    def check_book(self, book: Book, skip_check: bool = False) -> bool:
        """
        This function checks the book against the index. It returns a boolean that indicates whether the
        book data (e.g., annotations) should be further fetched or not.

        Note that upon checking for the existence of a book, the function only looks up information based
        on the book's ASIN.

        The function involves some user interaction via stdin/out to prompt users whether they want to fetch
        the latest book data and/or update the index.

        WARN: They may be some inconsistencies between the exported markdown (if any) and the index file if a
        user decides to update the index but not fetch the book. However, this could be useful to avoid
        keep getting prompts.
        """

        # Generate the current time in case we want to update the index
        current_datetime = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

        # WARN: This could be problematic if someone tampers with the index file manually and adds a book
        #       with a duplicate ASIN. However, we ignore it now since it is not an expected behavior.
        for indexed_book in self.books:
            if indexed_book.info.asin != book.asin:
                continue

            indexed_book.checked = True

            # Found a matching ASIN

            # If the metadata stays the same, then we could safely assume that a book has not been modified
            # since the last fetch. By "modify", we refer to the `last_opened_date` in the book, which would
            # change if we open the book (e.g., to read again or add new annotations).
            #
            # WARN: This could potentially has some issues since the "last_opened_date" only includes the
            #       exact date, but not the time. Hence, if someone fetches a book in the morning and modifies
            #       it in the evening, we may not be able to detect the changes. To handle this case, a user
            #       can simply reopen the book on the next day, which will trigger the prompt again, or perhaps
            #       update some metadata in the index which could trigger a fetch prompt.
            if indexed_book.info == book:
                # Only skip if there's no special skip_check flag, which is usually used if one wants to re-export
                # the entire notebook (e.g., because of changes in note formatting).
                if not skip_check:
                    return False
            else:
                # The book metadata has been changed. In most cases, this is probably because a user re-opens the book.
                echo("\nFound a book that has been modified:")
                echo(f"- Old: {indexed_book.info}")
                echo(f"- New: {book}\n")

            # Ask the user first whether they want to fetch the updated annotations

            # If yes, then we will automatically update the index to reflect the latest metadata
            if skip_check or prompt_user("Do you want to fetch the latest data for this book?"):
                indexed_book.info = book
                indexed_book.last_updated_time = current_datetime
                return True

            # If no, then we need to ask users whether they want to update the metadata
            if prompt_user("Do you want to update the indexed metadata?"):
                indexed_book.info = book
                indexed_book.last_updated_time = current_datetime

            return False

        # A book couldn't be found on the index
        #
        # Note that if we decide to add a new book to the index, it will always be appended to the back of the
        # list. Maybe can consider to make the list sorted based on the last updated time in the future.

        echo("\nUnable to find information about the following book in the index:")
        echo(f"  {book}\n")

        # Ask the user first whether they want to fetch the book

        # Prepare the export item in case we need to update the index
        item = ExportItem(last_updated_time=current_datetime, info=book)
        item.checked = True

        # If yes, we will automatically update the index as well
        if skip_check or prompt_user("Do you want to fetch the book data?"):
            self.books.append(item)
            return True

        # If no, we ask the user whether they want to update the index.
        # This could be useful if they want to avoid keep getting prompts for a book that has not
        # been opened again.
        if prompt_user("Do you want to add the book to the index?"):
            self.books.append(item)

        return False

    def warn_unchecked_books(self):
        """
        Helper function to write a warning log if some books are left unchecked
        """
        for book in self.books:
            if not book.checked:
                echo(f"Warning: Book {book.info} has not been checked")


def export_to_markdown(
    output_file: str,
    book: Book,
    chapters: Optional[List[Chapter]] = None,
    annotations: Optional[List[Annotation]] = None,
    annotations_version: Optional[str] = None,
) -> None:
    """
    Exports the given book and annotation data to a Markdown file.

    Args:
        output_file (str): The path to the output Markdown file.
        book (Book): The Book object to be exported.
        annotation_list (AnnotationList): The list of annotations associated with the book.
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f'# {book.title}\n\n')

        # Write information about the book

        if book.subtitle:
            f.write(f'- Subtitle: {book.subtitle}\n')
        f.write(f"- Author(s): {book.author}\n")
        if book.image_url:
            f.write(f'- Image URL: {book.image_url}\n')
        if book.pdf_url:
            # Note that accessing the URL typically requires special params. Hence, it's already expected
            # to be downloaded separately.
            f.write(f'- PDF URL: {book.pdf_url}\n')
        if book.publication_date:
            f.write(f'- Publication date: {book.publication_date}\n')
        if book.purchase_date:
            f.write(f'- Purchase date: {book.purchase_date}\n')
        f.write(f"- Last opened date: {book.last_opened_date}\n")
        f.write(f"- ASIN: {book.asin}\n")
        f.write('\n')

        # Write chapters
        if chapters:
            f.write('## Contents\n\n')

            def write_chapters(chapters: List[Chapter], depth: int):
                for chapter in chapters:
                    f.write(f"{'  ' * depth}")
                    f.write(f"- {chapter.title}")

                    if chapter.start_ms:
                        start_time = format_duration_from_ms(chapter.start_ms)
                        end_time = format_duration_from_ms(chapter.end_ms)
                        f.write(f' [{start_time}, {end_time}]')

                    f.write('\n')
                    if chapter.subchapters:
                        write_chapters(chapter.subchapters, depth+1)

            write_chapters(chapters, 0)
            f.write('\n')

        # Write annotations
        if annotations:
            f.write('## Annotations\n\n')
            if annotations_version:
                f.write(f'Version: {annotations_version}\n')
            f.write('\n---\n\n')
            for annotation in annotations:
                # Metadata
                if annotation.created_at:
                    f.write(f'- Created: {annotation.created_at}')
                    if annotation.updated_at and annotation.updated_at != annotation.created_at:
                        f.write(f' | Updated: {annotation.updated_at}')
                    f.write('\n')
                if annotation.clip_start_ms:
                    # Note that this is only for Audible
                    start_time = format_duration_from_ms(
                        annotation.clip_start_ms)
                    end_time = format_duration_from_ms(annotation.clip_end_ms)
                    f.write(f'- Clip: [{start_time}, {end_time}]\n')
                if annotation.location:
                    # Note that this is only for Kindle
                    f.write('- ')
                    if annotation.page:
                        f.write(f'Page: {annotation.page} | ')
                    f.write(f'Location: {annotation.location} [(kindle link)]'
                            f'(kindle://book?action=open&asin={book.asin}&location={annotation.location})\n')

                # Main content
                f.write('\n')
                if annotation.highlight:
                    f.write(f"**{annotation.highlight_color} highlight:**\n")
                    f.write(f"> {annotation.highlight}\n")
                    f.write('\n')
                if annotation.note:
                    f.write("**Note:**\n")
                    f.write(f"{annotation.note}\n")

                f.write('\n---\n\n')


# ---
# Authentication
#
# The code in this section are originally from:
# https://github.com/mkb79/audible-cli/blob/59ec48189d32cf1e0054be05650f35d83bafdfdb/src/audible_cli/utils.py#L77
#
# Modifications have been made to adapt the code to our specific use case and requirements.
# ---


def prompt_captcha_callback(captcha_url: str) -> str:
    """Helper function for handling captcha."""

    echo("Captcha found")
    if click.confirm("Open Captcha with default image viewer", default=True):
        captcha = httpx.get(captcha_url).content
        f = io.BytesIO(captcha)
        img = Image.open(f)
        img.show()
    else:
        echo(
            "Please open the following url with a web browser "
            "to get the captcha:"
        )
        echo(captcha_url)

    guess = prompt("Answer for CAPTCHA")
    return str(guess).strip().lower()


def prompt_otp_callback() -> str:
    """Helper function for handling 2-factor authentication."""

    echo("2FA is activated for this account.")
    guess = prompt("Please enter OTP Code")
    return str(guess).strip().lower()


def prompt_external_callback(url: str) -> str:
    # import readline to prevent issues when input URL in
    # CLI prompt when using macOS
    try:
        import readline  # noqa
    except ImportError:
        pass

    return default_login_url_callback(url)


def build_auth_file(
    filename: Union[str, Path],
    username: Optional[str],
    password: Optional[str],
    country_code: str,
    file_password: Optional[str] = None,
    external_login: bool = False,
    with_username: bool = False
) -> None:
    echo()
    secho("Login with amazon to your audible account now.", bold=True)

    file_options = {"filename": Path(filename)}
    if file_password:
        file_options.update(
            password=file_password,
            encryption=DEFAULT_AUTH_FILE_ENCRYPTION
        )

    if external_login:
        auth = Authenticator.from_login_external(
            locale=country_code,
            with_username=with_username,
            login_url_callback=prompt_external_callback)
    else:
        auth = Authenticator.from_login(
            username=username,
            password=password,
            locale=country_code,
            captcha_callback=prompt_captcha_callback,
            otp_callback=prompt_otp_callback)

    echo()

    device_name = auth.device_info["device_name"]  # pylint: disable=unsubscriptable-object
    secho(f"Successfully registered {device_name}.", bold=True)

    if not filename.parent.exists():
        filename.parent.mkdir(parents=True)

    auth.to_file(**file_options)


# ---
# Downloader
# ---

class Downloader:
    """
    This code is based on the implementation found at:
    https://github.com/mkb79/audible-cli/blob/59ec48189d32cf1e0054be05650f35d83bafdfdb/src/audible_cli/utils.py#L170

    Modifications have been made to adapt the code to our specific use case and requirements.
    """

    def __init__(
        self,
        url: str,
        file: Union[Path, str],
        client: requests.Session,
        overwrite_existing: bool,
        content_type: Optional[Union[List[str], str]] = None
    ) -> None:
        self._url = url
        self._file = Path(file).resolve()
        self._tmp_file = self._file.with_suffix(".tmp")
        self._client = client
        self._overwrite_existing = overwrite_existing

        if isinstance(content_type, str):
            content_type = [content_type, ]
        self._expected_content_type = content_type

    def _file_okay(self):
        if not self._file.parent.is_dir():
            echo(f"Folder {self._file.parent} doesn't exists! Skip download")
            return False

        if self._file.exists() and not self._file.is_file():
            echo(f"Object {self._file} exists but is no file. Skip download")
            return False

        if self._file.is_file() and not self._overwrite_existing:
            echo(f"File {self._file} already exists. Skip download")
            return False

        return True

    def _postpare(self, elapsed, status_code, length, content_type):
        if not 200 <= status_code < 400:
            try:
                msg = self._tmp_file.read_text()
            except:  # pylint: disable=bare-except
                msg = "Unknown"
            echo(f"Error downloading {self._file}. Message: {msg}")
            return False

        if length is not None:
            downloaded_size = self._tmp_file.stat().st_size
            length = int(length)
            if downloaded_size != length:
                echo(
                    f"Error downloading {self._file}. File size missmatch. "
                    f"Expected size: {length}; Downloaded: {downloaded_size}"
                )
                return False

        if self._expected_content_type is not None:
            if content_type not in self._expected_content_type:
                try:
                    msg = self._tmp_file.read_text()
                except:  # pylint: disable=bare-except
                    msg = "Unknown"
                echo(
                    f"Error downloading {self._file}. Wrong content type. "
                    f"Expected type(s): {self._expected_content_type}; "
                    f"Got: {content_type}; Message: {msg}"
                )
                return False

        file = self._file
        tmp_file = self._tmp_file
        if file.exists() and self._overwrite_existing:
            i = 0
            while file.with_suffix(f"{file.suffix}.old.{i}").exists():
                i += 1
            file.rename(file.with_suffix(f"{file.suffix}.old.{i}"))
        tmp_file.rename(file)
        echo(f"File {self._file} downloaded in {elapsed}.")
        return True

    def _load(self):
        r = self._client.get(self._url, follow_redirects=True)
        length = r.headers.get("Content-Length")
        content_type = r.headers.get("Content-Type")
        with open(self._tmp_file, mode="wb") as f:
            f.write(r.content)
        return self._postpare(r.elapsed, r.status_code, length, content_type)

    def run(self):
        if not self._file_okay():
            return False
        try:
            self._load()
        finally:
            # Remove tmp file
            if self._tmp_file.exists():
                self._tmp_file.unlink()
