"""
A module for processing and managing Amazon data.
"""
from __future__ import annotations

import os.path
from typing import List, Optional
from datetime import datetime
from pathlib import Path

import getpass
import toml
from pydantic import BaseModel, Field  # pylint: disable=no-name-in-module

from audible import Authenticator
from audible.auth import detect_file_encryption

from ncli import constants
from ncli.utils import prompt_user, format_duration_from_ms


class Config(BaseModel):
    """
    Config for Amazon products.
    """
    auth_file: Optional[str] = None
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
        def dumps_with_newline(data):
            toml_str = toml.dumps(data)
            lines = toml_str.splitlines()
            formatted_lines = []

            for line in lines:
                if len(formatted_lines) > 0 and line.startswith("[["):
                    formatted_lines.append("")
                formatted_lines.append(line)

            formatted_lines.append("")  # newline at the end

            return "\n".join(formatted_lines)

        index_str = dumps_with_newline(self.dict())
        with open(path, "w", encoding='utf-8') as file:
            file.write(index_str)

    def check_book(self, book: Book) -> bool:
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
                return False

            # The book metadata has been changed. In most cases, this is probably because a user re-opens the book.
            print("\nFound a book that has been modified:")
            print(f"- Old: {indexed_book.info}")
            print(f"- New: {book}\n")

            # Ask the user first whether they want to fetch the updated annotations

            # If yes, then we will automatically update the index to reflect the latest metadata
            if prompt_user("Do you want to fetch the latest data for this book?"):
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

        print("\nUnable to find information about the following book in the index:")
        print(f"  {book}\n")

        # Ask the user first whether they want to fetch the book

        # Prepare the export item in case we need to update the index
        item = ExportItem(last_updated_time=current_datetime, info=book)
        item.checked = True

        # If yes, we will automatically update the index as well
        if prompt_user("Do you want to fetch the book data?"):
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
                print(f"Warning: Book {book.info} has not been checked")


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
                    f.write(f'Clip: [{start_time}, {end_time}]\n')
                if annotation.location:
                    # Note that this is only for Kindle
                    f.write('- ')
                    if annotation.page:
                        f.write(f'Page: {annotation.page} | ')
                    f.write(f'Location: {annotation.location} [(kindle link)]'
                            '(kindle://book?action=open&asin={book.asin}&location={annotation.location})\n')

                # Main content
                f.write('\n')
                if annotation.highlight:
                    f.write(f"**{annotation.highlight_color} highlight:**\n")
                    f.write(f"> {annotation.highlight}\n")
                    f.write('\n')
                if annotation.note:
                    f.write("**Note:**\n")
                    f.write(f"{annotation.note}\n")
                    f.write('\n')

                f.write('\n---\n\n')
