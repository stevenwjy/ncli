"""
A module for processing and managing Audible data.
"""

from typing import List, Optional
from pathlib import Path

import audible
from click import echo

from ncli.kit_amazon import Config, load_authenticator, \
    Book, Chapter, Annotation, ExportIndex, export_to_markdown, Downloader
from ncli.utils import extract_date, format_date

EXPORT_INDEX_FILE_NAME: str = "index.toml"


class Client:
    """
    A client for interacting with the Audible APIs.
    """

    client: audible.Client

    def __init__(self, client: audible.Client):
        self.client = client

    def close(self):
        """
        Close the client connection.
        """
        self.client.close()

    def get_books(self) -> List[Book]:
        """
        Fetches the list of books from the Audible library.

        Returns:
            list[Book]: A list of Book instances.
        """
        data = self.client.get("library")
        res: List[Book] = []

        item: dict
        for item in data['items']:
            # We will only consider book items here.
            # The following will skip other types of library items (e.g., podcast).
            if item['content_delivery_type'] not in ('SinglePartBook', 'MultiPartBook'):
                continue

            asin: str = item['asin']

            authors: List[dict] = item['authors']
            author_str: str = authors[0]['name']
            if len(authors) > 1:
                for i in range(1, len(authors)):
                    author_str += f", {authors[i]['name']}"

            def format_iso_date(iso_date: Optional[str]) -> Optional[str]:
                """
                Converts an ISO date into a simple date if present.
                """
                if iso_date is None:
                    return None
                return extract_date(iso_date)

            publication_date = format_iso_date(
                item.get('publication_datetime', None))
            purchase_date = format_iso_date(item.get('purchase_date', None))

            # Due to the design of Audible API, we need to make a separate call here to fetch the
            # last opened time.
            params = {'response_groups': 'last_position_heard'}
            metadata = self.client.get(
                f'content/{asin}/metadata', params=params)

            # Note that it is possible to have a book in the library that has been purchased or added
            # but has never been opened.
            last_opened_date = ''
            if metadata['content_metadata']['last_position_heard']['status'] == 'Exists':
                last_opened_date = format_date(
                    metadata['content_metadata']['last_position_heard']['last_updated'])

            res.append(Book(
                asin=asin,
                title=item['title'],
                subtitle=item.get('subtitle', None),
                author=author_str,
                image_url=item['product_images']['500'],
                pdf_url=item.get('pdf_url', None),
                publication_date=publication_date,
                purchase_date=purchase_date,
                last_opened_date=last_opened_date,
            ))

        return res

    def get_chapters(self, book: Book) -> List[Chapter]:
        """
        Fetches the list of chapters for a particular book.
        """
        params = {'response_groups': 'chapter_info'}
        metadata = self.client.get(
            f'content/{book.asin}/metadata', params=params)

        def parse_chapters(data: List[dict]) -> List[Chapter]:
            res = []
            for item in data:
                subchapters = None
                if 'chapters' in item:
                    subchapters = parse_chapters(item['chapters'])

                res.append(Chapter(
                    title=item['title'],
                    start_ms=item['start_offset_ms'],
                    end_ms=item['start_offset_ms']+item['length_ms'],
                    subchapters=subchapters,
                ))

            return res

        return parse_chapters(metadata['content_metadata']['chapter_info']['chapters'])

    def get_annotations(self, book: Book) -> tuple[str, List[Annotation]]:
        """
        Fetches the list of annotations for a particular book
        """
        params = {'type': 'AUDI', 'key': book.asin}
        try:
            response = self.client.get(
                "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/sidecar", params=params)

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Note that we may fail to retrieve annotations here if the book has never had
            # any annotations (e.g., new book).
            echo(
                f'Failed to retrieve annotations for book {book.title}, reason: {e}')
            return "", []

        annotations_version: str = response['md5']
        annotations: List[Annotation] = []

        clip_records = []
        note_records = []
        for record in response['payload'].get('records', []):
            if record['type'] == 'audible.clip':
                clip_records.append(record)
            elif record['type'] == 'audible.note':
                note_records.append(record)

        # Note records are our priority, since some notes somehow only have note but not clip.
        for record in note_records:
            note = record['text']
            created_at = format_date(record['creationTime'])
            updated_at = format_date(record['lastModificationTime'])

            # For note records, typically the start and end time are the same.
            clip_start_ms = int(record['startPosition'])
            clip_end_ms = int(record['endPosition'])

            annotations.append(Annotation(
                note=note,
                clip_start_ms=clip_start_ms,
                clip_end_ms=clip_end_ms,
                created_at=created_at,
                updated_at=updated_at,
            ))

        # Add clips. But if there's a note with the same start time, created time, updated time, and text,
        # we will just update it.
        for record in clip_records:
            note = None
            if 'metadata' in record and 'note' in record['metadata']:
                note = record['metadata']['note']

            created_at = format_date(record['creationTime'])
            updated_at = format_date(record['lastModificationTime'])

            clip_start_ms = int(record['startPosition'])
            clip_end_ms = int(record['endPosition'])

            annotation = Annotation(
                note=note,
                clip_start_ms=clip_start_ms,
                clip_end_ms=clip_end_ms,
                created_at=created_at,
                updated_at=updated_at,
            )

            # Look for similar annotation (based on note records). If any, we will just update it.
            # It is fine to perform O(N^2) loop here since the number of annotations are unlikely to be that many.
            match = False
            for existing_annotation in annotations:
                match = annotation.clip_start_ms == existing_annotation.clip_start_ms and \
                    annotation.note == existing_annotation.note
                if match:
                    # If a match is found, we will simply adjust some info based on the clips.
                    existing_annotation.created_at = annotation.created_at
                    existing_annotation.updated_at = annotation.updated_at
                    existing_annotation.clip_end_ms = clip_end_ms
                    break
            # If no match found, we will just insert the clip (without note)
            if not match:
                annotations.append(annotation)

        # Sort the annotations based on the clip start time to make it easier to read.
        # Somehow the data fetched here are not sorted by their clip time.
        sorted_annotations = sorted(
            annotations, key=lambda annotation: annotation.clip_start_ms)

        return annotations_version, sorted_annotations


def export(
    config: Config,
    target: Path,
    renew: bool,
):
    """
    Exports Audible data
    """
    auth = load_authenticator(config)
    audible_client = audible.Client(auth)
    client = Client(audible_client)

    book_library = client.get_books()

    index_file_path = target.joinpath(EXPORT_INDEX_FILE_NAME)
    export_index = ExportIndex.load_or_default(index_file_path)

    for book in book_library:
        if export_index.check_book(book, skip_check=renew):
            chapters = client.get_chapters(book)
            annotation_version, annotations = client.get_annotations(book)

            # Note that we will generate the book name using its title and use the ".md" extension since it is
            # a Markdown file.
            book_path = target.joinpath(f"{book.title}.md")

            export_to_markdown(
                book_path,
                book,
                chapters=chapters,
                annotations=annotations,
                annotations_version=annotation_version,
            )

            if book.pdf_url:
                # For some reason, we can't use the recorded pdf url to download,
                # since it would give 403 error.
                domain = audible_client.auth.locale.domain
                pdf_url = f'https://www.audible.{domain}/companion-file/{book.asin}'

                pdf_path = target.joinpath(f'{book.title}.pdf')

                downloader = Downloader(
                    # Note: we will always overwrite existing file
                    pdf_url, pdf_path, audible_client.session, True,
                    ["application/octet-stream", "application/pdf"]
                )
                downloader.run()

            # Print some info if all books are expected to be exported.
            if renew:
                echo(f'Exported book: {book}')

    # Log warning(s) for book(s) that are left unchecked.
    if not renew:
        export_index.warn_unchecked_books()

    # Save back the index
    export_index.save(index_file_path)

    # Close after completing the export
    client.close()
