"""
A module for processing and managing Audible data.
"""

from typing import List, Optional
from pathlib import Path

import audible

from ncli.kit_amazon import Config, Authenticator, load_authenticator, \
    Book, Chapter, Annotation, ExportIndex, export_to_markdown
from ncli.utils import extract_date, format_date

EXPORT_INDEX_FILE_NAME: str = "index.toml"


class Client:
    """
    A client for interacting with the Audible APIs.
    """

    client: audible.Client

    def __init__(self, auth: Authenticator):
        self.client = audible.Client(auth)

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
        response = self.client.get(
            "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/sidecar", params=params)

        annotations_version: str = response['md5']
        annotations: List[Annotation] = []

        for record in response['payload'].get('records', []):
            if record['record_type'] != 'audible.clip':
                continue
            note = None
            if 'metadata' in record and 'note' in record['metadata']:
                note = record['metadata']['note']

            created_at = format_date(record['creation_time'])
            updated_at = format_date(record['last_modification_time'])

            annotations.append(Annotation(
                note=note,
                clip_start_ms=int(record['start_position']),
                clip_end_ms=int(record['end_position']),
                created_at=created_at,
                updated_at=updated_at,
            ))

        return annotations_version, annotations


def export(
    config: Config,
    target: Path,
):
    """
    Exports Audible data
    """
    auth = load_authenticator(config)
    client = Client(auth)

    book_library = client.get_books()

    index_file_path = target.joinpath(EXPORT_INDEX_FILE_NAME)
    export_index = ExportIndex.load_or_default(index_file_path)

    for book in book_library:
        if export_index.check_book(book):
            annotations = client.get_annotations(book)

            # Note that we will generate the book name using its title and use the ".md" extension since it is
            # a Markdown file.
            book_path = target.joinpath(f"{book.title}.md")

            export_to_markdown(book_path, book, annotations=annotations)

            # TODO: Add URL downloader

    # Log warning(s) for book(s) that are left unchecked.
    export_index.warn_unchecked_books()

    # Save back the index
    export_index.save(index_file_path)

    # Close after completing the export
    client.close()
