# This specific file is part of the 'ncli' project and it is licensed under the AGPL-3.0 License.
# Please see the accompanying LICENSE-AGPL-3.0 file for more details.

"""
A module for processing and managing Amazon data.
"""

from __future__ import annotations

import getpass
import io
import math
import os.path
from datetime import datetime
from pathlib import Path

import click
import httpx
import toml
from audible import Authenticator
from audible.auth import detect_file_encryption
from audible.login import default_login_url_callback
from click import echo, prompt, secho
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from tqdm import tqdm

from ncli import constants
from ncli.utils import format_duration_from_ms, prompt_user, toml_dumps_with_newline


AVAILABLE_COUNTRY_CODES: list[str] = [
    "us",
    "ca",
    "uk",
    "au",
    "fr",
    "de",
    "es",
    "jp",
    "it",
    "in",
]
DEFAULT_AUTH_FILE_EXTENSION: str = "json"
DEFAULT_AUTH_FILE_ENCRYPTION: str = "json"

MAX_AUTH_TRIES = 3


class Config(BaseModel):
    """
    Config for Amazon products.
    """

    auth_file: str = ""
    country_code: str = "us"


def load_authenticator(config: Config) -> Authenticator:
    """
    Loads authenticator
    """
    if config.auth_file:
        file_path = constants.BASE_PATH.joinpath(config.auth_file)
        pwd = None
        if detect_file_encryption(file_path):
            pwd = getpass.getpass("Enter auth file password: ")

        num_try = 1
        while True:
            try:
                return Authenticator.from_file(file_path, pwd)
            except ValueError as e:
                if pwd and num_try < MAX_AUTH_TRIES:
                    echo("Failed to decrypt the auth file. Wrong password?")
                    pwd = getpass.getpass("Enter auth file password: ")
                    num_try += 1
                    continue
                raise e

    raise ValueError("Config without auth file not supported")


class Book(BaseModel):
    """
    Represents a book with metadata.
    """

    asin: str = ""
    title: str = ""
    subtitle: str | None = None

    # Author of the book.
    #
    # For a book that has more than one authors, we concatenate their names (comma-separated) into
    # a single string here for simplicity.
    author: str = ""

    # URL for the book cover image
    image_url: str = ""
    # URL for the accompanying PDF (only for Audible).
    # Note that the URL may require some cookies to be accessed.
    pdf_url: str | None = None

    # Publication date for the book. Currently only available for Audible.
    publication_date: str | None = None
    # Purchase date for the book. Currently only available for Audible.
    purchase_date: str | None = None

    # Last opened date represents:
    # - Last time the book is read for Kindle.
    # - Last time the book is listened for Audible (based on last update time for the last listened position).
    last_opened_date: str = ""

    # Only for Audible: indicates whether the audiobook is downloadable.
    is_downloadable: bool | None = None

    def is_published(self) -> bool:
        if not self.publication_date:
            return False

        date_pub = datetime.strptime(self.publication_date, "%Y-%m-%d")
        # TODO: Shall we use timezone for the kindle auth?
        date_now = datetime.now()
        return date_now > date_pub


class Chapter(BaseModel):
    """
    Represents a chapter from a book.
    """

    title: str = ""

    # For Audible
    #
    # The clip start and end values are in milisecond offset w.r.t. the beginning time.
    start_ms: int | None = None
    end_ms: int | None = None

    subchapters: list[Chapter] | None = None


class Annotation(BaseModel):
    """
    Represents a single annotation (highlight and/or note) from a book.
    """

    # For Kindle
    highlight: str | None = None
    highlight_color: str | None = None

    # For Kindle and Audible
    note: str | None = None

    # For Kindle
    #
    # Note that location is guaranteed to exist for Kindle.
    location: int | None = None
    page: int | None = None

    # For Audible
    #
    # The clip start and end values are in milisecond offset w.r.t. the beginning time.
    clip_start_ms: int | None = None
    clip_end_ms: int | None = None

    # Currently only available for Audible
    created_at: str | None = None
    updated_at: str | None = None


class ExportItem(BaseModel):
    """
    Represents an item to be exported, containing a Book and its associated metadata.
    """

    last_updated_time: str

    is_downloaded: bool = False

    info: Book

    checked: bool = Field(default=False, exclude=True)

    model_config = ConfigDict(json_schema_extra={"exclude": ["checked"]})


class ExportIndex(BaseModel):
    """
    Represents an index of exported items.
    """

    books: list[ExportItem]

    @staticmethod
    def load_or_default(path: Path):
        """
        Load the export index or default to an empty state if there is no such file.
        """
        if not os.path.exists(path):
            return ExportIndex(books=[])

        with open(path, encoding="utf-8") as file:
            index_str = file.read()
        index = toml.loads(index_str)
        return ExportIndex(**index)

    def save(self, path: Path):
        """
        Save the export index into the specified path.
        """
        index_str = toml_dumps_with_newline(
            self.model_dump(
                exclude_none=True,
                exclude_defaults=True,
            )
        )
        with open(path, "w", encoding="utf-8") as file:
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
            # TODO: Ensure the uniqueness of the title first?
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
    chapters: list[Chapter] | None = None,
    annotations: list[Annotation] | None = None,
    annotations_version: str | None = None,
) -> None:
    """
    Exports the given book and annotation data to a Markdown file.

    Args:
        output_file (str): The path to the output Markdown file.
        book (Book): The Book object to be exported.
        annotation_list (AnnotationList): The list of annotations associated with the book.
    """
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {book.title}\n\n")

        # Write information about the book

        if book.subtitle:
            f.write(f"- Subtitle: {book.subtitle}\n")
        f.write(f"- Author(s): {book.author}\n")
        if book.image_url:
            f.write(f"- Image URL: {book.image_url}\n")
        if book.pdf_url:
            # Note that accessing the URL typically requires special params. Hence, it's already expected
            # to be downloaded separately.
            f.write(f"- PDF URL: {book.pdf_url}\n")
        if book.publication_date:
            f.write(f"- Publication date: {book.publication_date}\n")
        if book.purchase_date:
            f.write(f"- Purchase date: {book.purchase_date}\n")
        f.write(f"- Last opened date: {book.last_opened_date}\n")
        f.write(f"- ASIN: {book.asin}\n")
        f.write("\n")

        # Write chapters
        if chapters:
            f.write("## Contents\n\n")

            def write_chapters(chapters: list[Chapter], depth: int):
                for chapter in chapters:
                    f.write(f"{'  ' * depth}")
                    f.write(f"- {chapter.title}")

                    if chapter.start_ms:
                        start_time = format_duration_from_ms(chapter.start_ms)
                        end_time = format_duration_from_ms(chapter.end_ms)
                        f.write(f" [{start_time}, {end_time}]")

                    f.write("\n")
                    if chapter.subchapters:
                        write_chapters(chapter.subchapters, depth + 1)

            write_chapters(chapters, 0)
            f.write("\n")

        # Write annotations
        if annotations:
            f.write("## Annotations\n\n")
            if annotations_version:
                f.write(f"Version: {annotations_version}\n")
            f.write("\n---\n\n")
            for annotation in annotations:
                # Metadata
                if annotation.created_at:
                    f.write(f"- Created: {annotation.created_at}")
                    if annotation.updated_at and annotation.updated_at != annotation.created_at:
                        f.write(f" | Updated: {annotation.updated_at}")
                    f.write("\n")
                if annotation.clip_start_ms:
                    # Note that this is only for Audible
                    start_time = format_duration_from_ms(annotation.clip_start_ms)
                    end_time = format_duration_from_ms(annotation.clip_end_ms)
                    f.write(f"- Clip: [{start_time}, {end_time}]\n")
                if annotation.location:
                    # Note that this is only for Kindle
                    f.write("- ")
                    if annotation.page:
                        f.write(f"Page: {annotation.page} | ")
                    f.write(
                        f"Location: {annotation.location} [(kindle link)]"
                        f"(kindle://book?action=open&asin={book.asin}&location={annotation.location})\n"
                    )

                # Main content
                f.write("\n")
                if annotation.highlight:
                    f.write(f"**{annotation.highlight_color} highlight:**\n")
                    f.write(f"> {annotation.highlight}\n")
                    f.write("\n")
                if annotation.note:
                    f.write("**Note:**\n")
                    f.write(f"{annotation.note}\n")

                f.write("\n---\n\n")


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
        echo("Please open the following url with a web browser " "to get the captcha:")
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
    filename: str | Path,
    username: str | None,
    password: str | None,
    country_code: str,
    file_password: str | None = None,
    external_login: bool = False,
    with_username: bool = False,
) -> None:
    echo()
    secho("Login with amazon to your audible account now.", bold=True)

    file_options = {"filename": Path(filename)}
    if file_password:
        file_options.update(password=file_password, encryption=DEFAULT_AUTH_FILE_ENCRYPTION)

    if external_login:
        auth = Authenticator.from_login_external(
            locale=country_code,
            with_username=with_username,
            login_url_callback=prompt_external_callback,
        )
    else:
        auth = Authenticator.from_login(
            username=username,
            password=password,
            locale=country_code,
            captcha_callback=prompt_captcha_callback,
            otp_callback=prompt_otp_callback,
        )

    echo()

    device_name = auth.device_info["device_name"]
    secho(f"Successfully registered {device_name}.", bold=True)

    if not filename.parent.exists():
        filename.parent.mkdir(parents=True)

    auth.to_file(**file_options)


# ---
# Downloader
# ---


class Downloader:
    """
    Downloader for a remote object file.

    The code here was inspired from:
    https://github.com/mkb79/audible-cli/blob/b3adb9a33157322cd6d79ff59f5dacf06dc3e034/src/audible_cli/downloader.py#L286

    However, lots of modifications have been made based on our use cases.
    """

    def __init__(
        self,
        url: str,
        path: Path | str,
        client: httpx.Client,
        headers: dict[str, str] | None = None,
        desc: str = "file",
        # Chunk size for streaming
        chunk_size=64 * 1024,  # 64KB
        # If a past attempt to download the file is found and the endpoint
        # supports range requests, then the downloader should prefer to just
        # resume the download instead of starting from zero.
        prefer_continue=True,
        # Expected potential types for the downloaded file.
        expected_types: list[str] | str | None = None,
    ) -> None:
        self._url = url
        self._target_path = Path(path).resolve()
        self._tmp_path = self._target_path.with_suffix(".tmp")

        self._client = client
        self._headers = {} if headers is None else headers

        self._desc = desc
        self._chunk_size = chunk_size
        self._prefer_continue = prefer_continue

        if isinstance(expected_types, str):
            expected_types = [expected_types]
        self._expected_content_types = expected_types

    # Returns whether the file has been successfully downloaded.
    def run(self):
        self._validate_paths()

        if self._target_path.exists():
            # Note that this is guaranteed to be the "full" version because
            # partial download always goes to a tmp file first.
            echo(f"Path {self._target_path} already exists. Skip download for {self._desc}.")
            return

        start_byte, est_size, mode = 0, math.inf, "wb"
        if self._prefer_continue:
            accepts_ranges, est_size = self._check_support_range_reqs()
            # Note that we always download to the tmp path first.
            # TODO: Should we check the ETag header for integrity?
            if self._tmp_path.exists() and accepts_ranges:
                start_byte = os.path.getsize(self._tmp_path)
                mode = "ab"

        if start_byte < est_size:
            headers = self._headers.copy()
            if start_byte > 0:
                headers["Range"] = f"bytes={start_byte}-"

            response: httpx.Response
            with self._client.stream("GET", self._url, headers=headers, follow_redirects=True) as response:
                response.raise_for_status()

                content_type = response.headers.get("Content-Type")
                if self._expected_content_types is not None and content_type not in self._expected_content_types:
                    raise Exception(
                        f"Downloaded content type '{content_type}' is not within {self._expected_content_types}"
                    )
                total_size = int(response.headers.get("Content-Length", 0))

                with tqdm(
                    total=total_size,
                    initial=start_byte,
                    unit="iB",
                    unit_scale=True,
                    unit_divisor=1024,  # For binary multiples (KiB, MiB, etc)
                    desc=f"Downloading {self._desc}",
                ) as progress_bar:
                    with open(self._tmp_path, mode=mode) as f:
                        for chunk in response.iter_bytes(chunk_size=self._chunk_size):
                            f.write(chunk)
                            progress_bar.update(len(chunk))
                        progress_bar.close()

        self._tmp_path.rename(self._target_path)

        # Remove tmp file
        if self._tmp_path.exists():
            self._tmp_path.unlink()

    def _validate_paths(self):
        if not self._target_path.parent.is_dir():
            raise Exception(f"Dir {self._target_path.parent} does not exist. Skip download")

        if self._target_path.exists() and not self._target_path.is_file():
            raise Exception(f"Path {self._target_path} exists but is not a file.")

        if self._tmp_path.exists() and not self._tmp_path.is_file():
            raise (f"Temp path {self._tmp_path} exists but is not a file.")

    def _check_support_range_reqs(self) -> tuple[bool, int]:
        """Check if server supports resume and get total file size."""
        # We are using GET request here (without loading the body) as HEAD
        # requests can sometimes be slower.
        # Ref: https://github.com/mkb79/audible-cli/pull/196
        response: httpx.Response
        with self._client.stream("GET", self._url, headers=self._headers, follow_redirects=True) as response:
            response.raise_for_status()

            # Update URL if there's redirect so that we don't need to go through
            # redirection again later on.
            if response.request.url != self._url:
                self._url = response.request.url

            accepts_ranges = response.headers.get("Accept-Ranges") == "bytes"
            total_size = int(response.headers.get("Content-Length", 0))
            return accepts_ranges, total_size
