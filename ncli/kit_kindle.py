"""
A module for processing and managing Kindle data.
"""

from typing import List
from pathlib import Path

import requests

from bs4 import BeautifulSoup

from ncli.kit_amazon import Config, Authenticator, load_authenticator, \
    Book, Annotation, ExportIndex, export_to_markdown

KINDLE_HIGHLIGHTS_URL: str = 'https://read.amazon.com/notebook'
EXPORT_INDEX_FILE_NAME: str = "index.toml"


class Client:
    """
    A client for interacting with the Kindle Highlights website.

    Attributes:
        email (str): The email address associated with the Amazon account.
        password (str): The password for the Amazon account.
    """

    def __init__(self, auth: Authenticator):
        if auth.website_cookies is None:
            raise ValueError('unexpected: auth does not have website_cookies')

        self.auth = auth
        self.session = requests.Session()
        self.session.cookies.update(auth.website_cookies)

    def close(self):
        """
        Close the client connection.
        """
        self.session.close()

    def get_books(self) -> List[Book]:
        """
        Fetches the list of books from the Kindle Highlights website.

        Returns:
            list[Book]: A list of Book instances.
        """
        kindle_highlights_response = self.session.get(KINDLE_HIGHLIGHTS_URL)

        soup = BeautifulSoup(kindle_highlights_response.content, 'html.parser')

        book_entries = soup.find_all(
            'div', {'class': 'kp-notebook-library-each-book'})
        books = []

        for book_entry in book_entries:
            # Retrieve the Amazon Standard Identification Number (ASIN)
            #
            # We need this value if we want to fetch other information about the book from Amazon (e.g., highlights).
            asin = book_entry['id']

            # Retrieve the book title and subtitle if present
            #
            # Note that some books have the following format for the title: "<title>: <subtitle>".
            # Hence, we want to identify the subtitle and separate it from the main title if there is any.
            # The reason is because we want to save a book only based on its title as the file name.
            book_title = book_entry.find('h2').get_text(strip=True)
            title_parts = book_title.split(":", 1)
            title = title_parts[0].strip()
            subtitle = title_parts[1].strip() if len(title_parts) > 1 else None

            # Retrieve the author
            #
            # In the website, the author is written in the following format: "By: <author>".
            # Hence, we need to remove the "By: " prefix.
            book_author = book_entry.find('p').get_text(strip=True)
            author_parts = book_author.split(":", 1)
            author = author_parts[1].strip() if len(
                author_parts) > 1 else author_parts[0].strip()

            # Retrieve the image URL
            #
            # Note that the url will be using Amazon CDN and it is not guaranteed for long time use as they could
            # change over time.
            image_url = book_entry.find('img')['src']

            # Retrieve the last opened date
            #
            # Note that we keep it as a string, since this value is probably not that useful given that we may
            # occasionally open a book, but not adding any new annotations.
            last_opened_date = book_entry.find('input')['value']

            # Construct the book object based on all the information that we have
            book = Book(asin=asin, title=title, subtitle=subtitle, author=author,
                        image_url=image_url, last_opened_date=last_opened_date)
            books.append(book)

        return books

    def get_annotations(self, book: Book) -> List[Annotation]:
        """
        Fetches the annotations for a given book.
        """
        book_asin = book.asin

        first_page = True
        page_token = None
        page_limit_state = None

        session = requests.Session()
        session.cookies.update(self.auth.website_cookies)

        result = []

        while first_page or page_token:
            if first_page:
                url = f'https://read.amazon.com/notebook?asin={book_asin}&contentLimitState=&='
                first_page = False
            else:
                url = f'https://read.amazon.com/notebook?asin={book_asin}&token={page_token}&contentLimitState={page_limit_state}&='

            annotations_response = session.get(url)

            soup = BeautifulSoup(annotations_response.content, 'html.parser')

            # Next page token and limit state
            page_token = soup.find(
                'input', {'class': 'kp-notebook-annotations-next-page-start'}).get('value', default=None)
            page_limit_state = soup.find(
                'input', {'class': 'kp-notebook-content-limit-state'}).get('value', default=None)

            annotations_element = soup.find(id='kp-notebook-annotations')
            if annotations_element:
                annotations = annotations_element.find_all(
                    'div', {'class': 'kp-notebook-row-separator'})
            else:
                annotations = soup.find_all(
                    'div', {'class': 'kp-notebook-row-separator'})

            for annotation in annotations:
                highlight = None
                highlight_color = None
                note = None
                page = None

                # Retrieve the highlight
                highlight_element = annotation.find(
                    'span', {'id': 'highlight'})
                if highlight_element:
                    highlight = highlight_element.get_text(strip=True)

                    # Retrieve the highlight header
                    #
                    # The header will be one of the following formats:
                    # 1. "<color> annotation | Page: <page>" if there's a page number
                    # 2. "<color> annotation | Location: <location>" if there's no page number
                    #
                    # However, since we can always get the location from another field, we won't retrieve the location
                    # for the second case.
                    highlight_header = annotation.find(
                        'span', {'id': 'annotationHighlightHeader'}).get_text(strip=True)
                    header_parts = highlight_header.split("|", 1)
                    color_parts = header_parts[0].strip().split(" ", 1)
                    page_parts = header_parts[1].strip().split(":\xa0", 1)

                    # We can retrieve highlight color and potentially the page number here
                    highlight_color = color_parts[0].strip()
                    if page_parts[0] == "Page":
                        page = int(page_parts[1].strip())

                # Retrieve the note
                #
                # Note that the Kindle notebook page is a bit weird since it will always have the note element.
                # In order to find out about its existence, we need to check the length.
                note_str = annotation.find(
                    'span', {'id': 'note'}).get_text(strip=True)
                if note_str:
                    note = note_str

                    # If there is no highlight, check the page number using the note header
                    if highlight is None:
                        # Similar with the highlight header, it will be one of the following formats:
                        # 1. "Note | Page: <page>" if there's a page number
                        # 2. "Note | Location: <location>" if there's no page number
                        #
                        # Only the first case is useful.
                        note_header = annotation.find(
                            'span', {'id': 'annotationNoteHeader'}).get_text(strip=True)
                        header_parts = note_header.split("|", 1)
                        page_parts = header_parts[1].strip().split(":\xa0", 1)

                        if page_parts[0] == "Page":
                            page = int(page_parts[1].strip())

                # Retrieve the location
                location = int(annotation.find(
                    'input', {'id': 'kp-annotation-location'})['value'])

                result.append(Annotation(
                    highlight=highlight,
                    highlight_color=highlight_color,
                    note=note,
                    page=page,
                    location=location
                ))

        return result


def export(
    config: Config,
    target: Path,
    skip_check: bool,
) -> None:
    """
    Exports kindle data
    """
    auth = load_authenticator(config)
    client = Client(auth)
    book_library = client.get_books()

    index_file_path = target.joinpath(EXPORT_INDEX_FILE_NAME)
    export_index = ExportIndex.load_or_default(index_file_path)

    for book in book_library:
        if export_index.check_book(book, skip_check=skip_check):
            annotations = client.get_annotations(book)

            # Note that we will generate the book name using its title and use the ".md" extension since it is
            # a Markdown file.
            book_path = target.joinpath(f"{book.title}.md")

            export_to_markdown(book_path, book, annotations=annotations)

            # Print some info if all books are expected to be exported.
            if skip_check:
                print(f'Exported book: {book}')

    # Log warning(s) for book(s) that are left unchecked.
    if not skip_check:
        export_index.warn_unchecked_books()

    # Save back the index
    export_index.save(index_file_path)

    # Close after completing the export
    client.close()
