# This specific file is part of the 'ncli' project and it is licensed under the AGPL-3.0 License.
# Please see the accompanying LICENSE-AGPL-3.0 file for more details.

"""
A module for processing and managing Audible data.
"""

import json
import math
import secrets
from pathlib import Path
from typing import Any

import audible
import ffmpeg
import httpx
from audible.aescipher import decrypt_voucher_from_licenserequest
from audible.client import convert_response_content, raise_for_status
from click import echo

from ncli.kit_amazon import (
    Annotation,
    Book,
    Chapter,
    Config,
    Downloader,
    ExportIndex,
    export_to_markdown,
    load_authenticator,
)
from ncli.utils import ProgressFfmpeg, extract_date, format_date, prompt_user_num


EXPORT_INDEX_FILE_NAME: str = "index.toml"

BASE_CLIENT_HEADERS = {
    "User-Agent": "Audible/671 CFNetwork/1240.0.4 Darwin/20.6.0",
}

AVAILABLE_AAXC_QUALITY: list[str] = ["best", "high", "normal"]
AVAILABLE_COVER_SIZES: list[str] = ["252", "315", "360", "408", "500", "558", "570", "882", "900", "1215"]

REQUESTED_RESPONSE_GROUPS = ", ".join(
    [
        # Used defaults
        "product_desc, product_attrs, media, pdf_url",
        # Additional requested fields
        "customer_rights",  # for checking whether the audiobook is downloadable
    ]
)
PAGE_SIZE = 20

# Documenting this in case needed in the future.
UNUSED_RESPONSE_GROUPS = ", ".join(
    [
        # Unused defaults
        "contributors, category_ladders",
        # Other possible fields
        "product_extended_attrs, product_plans, product_plan_details, product_details",
        "sku, series, price, relationships, origin_asin, sample, ws4v, claim_code_url, periodicals",
        "categories, category_ladders, rating, reviews, review_attrs, provided_review",
        "in_wishlist, listening_status, order_details, percent_complete",
        "is_archived, is_downloaded, is_finished, is_playable, is_removable, is_returnable, is_visible",
    ]
)

AUDIO_BITRATE = "192k"


class Client:
    """
    A client for interacting with the Audible APIs.
    """

    client: audible.Client

    def __init__(self, client: audible.Client):
        self.client = client

        # Must set some client headers properly (e.g., user-agent).
        # Otherwise, the requests can be blocked by Audible's API.
        self.client.session.headers.update(BASE_CLIENT_HEADERS)

        # The default timeout (10s) seems a bit too low on some cases.
        # Hence, for now, we extend the timeout for all operations.
        self.client.session.timeout = httpx.Timeout(30)

    def close(self):
        """
        Close the client connection.
        """
        self.client.close()

    def get_books(
        self,
        cover_size="1215",
    ) -> list[Book]:
        """
        Fetches the list of books from the Audible library.

        Returns:
            list[Book]: A list of Book instances.
        """
        if cover_size not in AVAILABLE_COVER_SIZES:
            raise ValueError(f"book cover size {cover_size} is not in {AVAILABLE_COVER_SIZES}")

        def response_callback(resp: httpx.Response) -> Any:
            raise_for_status(resp)
            total_count = resp.headers.get("total-count", 1)
            return convert_response_content(resp), int(total_count)

        res: list[Book] = []
        page_num = 1
        while True:
            data, total_count = self.client.get(
                "library",
                response_callback=response_callback,
                image_sizes=cover_size,
                response_groups=REQUESTED_RESPONSE_GROUPS,
                page=page_num,
                num_results=PAGE_SIZE,
            )
            num_pages = int(math.ceil(total_count / PAGE_SIZE))

            item: dict
            for item in data["items"]:
                # We will only consider book items here.
                # The following will skip other types of library items (e.g., podcast).
                if item["content_delivery_type"] not in ("SinglePartBook", "MultiPartBook"):
                    continue
                res.append(self._get_book_from_audible_library_item(item))

            if page_num >= num_pages:
                break
            page_num += 1

        return res

    def _get_book_from_audible_library_item(self, item: dict) -> Book:
        if item["content_delivery_type"] not in ("SinglePartBook", "MultiPartBook"):
            raise ValueError("content type must be either SinglePartBook or MultiPartBook")

        asin: str = item["asin"]

        authors: list[dict] = item["authors"]
        author_str: str = authors[0]["name"]
        if len(authors) > 1:
            for i in range(1, len(authors)):
                author_str += f", {authors[i]['name']}"

        def format_iso_date(iso_date: str | None) -> str | None:
            """
            Converts an ISO date into a simple date if present.
            """
            if iso_date is None:
                return None
            return extract_date(iso_date)

        publication_date = format_iso_date(item.get("publication_datetime", None))
        purchase_date = format_iso_date(item.get("purchase_date", None))

        # Due to the design of Audible API, we need to make a separate call here to fetch the
        # last opened time.
        params = {"response_groups": "last_position_heard"}
        metadata = self.client.get(f"content/{asin}/metadata", params=params)

        # Note that it is possible to have a book in the library that has been purchased or added
        # but has never been opened.
        last_opened_date = ""
        if metadata["content_metadata"]["last_position_heard"]["status"] == "Exists":
            last_opened_date = format_date(metadata["content_metadata"]["last_position_heard"]["last_updated"])

        return Book(
            asin=asin,
            title=item["title"],
            subtitle=item.get("subtitle", None),
            author=author_str,
            # For simplicity, we currently always take the maximum
            # possible size.
            image_url=item["product_images"]["1215"],
            pdf_url=item.get("pdf_url", None),
            publication_date=publication_date,
            purchase_date=purchase_date,
            last_opened_date=last_opened_date,
            is_downloadable=item["customer_rights"]["is_consumable_offline"],
        )

    def get_chapters(self, book: Book) -> list[Chapter]:
        """
        Fetches the list of chapters for a particular book.
        """
        params = {"response_groups": "chapter_info"}
        metadata = self.client.get(f"content/{book.asin}/metadata", params=params)

        def parse_chapters(data: list[dict]) -> list[Chapter]:
            res = []
            for item in data:
                subchapters = None
                if "chapters" in item:
                    subchapters = parse_chapters(item["chapters"])

                res.append(
                    Chapter(
                        title=item["title"],
                        start_ms=item["start_offset_ms"],
                        end_ms=item["start_offset_ms"] + item["length_ms"],
                        subchapters=subchapters,
                    )
                )

            return res

        return parse_chapters(metadata["content_metadata"]["chapter_info"]["chapters"])

    def get_annotations(self, book: Book) -> tuple[str, list[Annotation]]:
        """
        Fetches the list of annotations for a particular book
        """
        params = {"type": "AUDI", "key": book.asin}
        try:
            response = self.client.get(
                "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/sidecar",
                params=params,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Note that we may fail to retrieve annotations here if the book has never had
            # any annotations (e.g., new book).
            echo(f"Failed to retrieve annotations for book {book.title}, reason: {e}")
            return "", []

        annotations_version: str = response["md5"]
        annotations: list[Annotation] = []

        clip_records = []
        note_records = []
        for record in response["payload"].get("records", []):
            if record["type"] == "audible.clip":
                clip_records.append(record)
            elif record["type"] == "audible.note":
                note_records.append(record)

        # Note records are our priority, since some notes somehow only have note but not clip.
        for record in note_records:
            note = record["text"]
            created_at = format_date(record["creationTime"])
            updated_at = format_date(record["lastModificationTime"])

            # For note records, typically the start and end time are the same.
            clip_start_ms = int(record["startPosition"])
            clip_end_ms = int(record["endPosition"])

            annotations.append(
                Annotation(
                    note=note,
                    clip_start_ms=clip_start_ms,
                    clip_end_ms=clip_end_ms,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )

        # Add clips. But if there's a note with the same start time, created time, updated time, and text,
        # we will just update it.
        for record in clip_records:
            note = None
            if "metadata" in record and "note" in record["metadata"]:
                note = record["metadata"]["note"]

            created_at = format_date(record["creationTime"])
            updated_at = format_date(record["lastModificationTime"])

            clip_start_ms = int(record["startPosition"])
            clip_end_ms = int(record["endPosition"])

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
                match = (
                    annotation.clip_start_ms == existing_annotation.clip_start_ms
                    and annotation.note == existing_annotation.note
                )
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
        sorted_annotations = sorted(annotations, key=lambda annotation: annotation.clip_start_ms)

        return annotations_version, sorted_annotations

    def get_pdf(self, book: Book, target_dir: Path):
        if not book.pdf_url:
            raise ValueError(f"book {book.title} does not have pdf url")
        if not target_dir.is_dir():
            raise ValueError(f"target dir {target_dir} is not a directory")

        target_path = target_dir.joinpath(f"{book.title}.pdf")
        if target_path.exists():
            echo(f"PDF for {book.title} already exists. Skip download.")
            return

        # For some reason, we can't use the recorded pdf url to download,
        # since it would give 403 error.
        domain = self.client.auth.locale.domain
        pdf_url = f"https://www.audible.{domain}/companion-file/{book.asin}"

        Downloader(
            pdf_url,
            target_path,
            self.client.session,
            desc="PDF",
            expected_types=["application/octet-stream", "application/pdf"],
        ).run()

    def get_cover(self, book: Book, target_dir: Path) -> Path | None:
        if not book.image_url:
            echo(f"Unable to find cover for book {book.title}")
            return None
        if not target_dir.is_dir():
            raise ValueError(f"target dir {target_dir} is not a directory")

        # Example valid URL: https://m.media-amazon.com/images/I/AAAAAAAA._SL500_.jpg
        # Our goal is just to take '._SL500.jpg'.
        parts = book.image_url.rsplit(".", 2)
        if len(parts) < 3:
            raise Exception(f"unexpected audible image URL: {book.image_url}")
        suffixes = ".".join(parts[-2:])

        target_path = target_dir / f"{book.title}.{suffixes}"
        Downloader(
            book.image_url,
            target_path,
            self.client.session,
            desc="cover image",
            expected_types=["image/jpeg"],
        ).run()

        return target_path

    # Ref:
    # - https://github.com/mkb79/audible-cli/blob/b3adb9a33157322cd6d79ff59f5dacf06dc3e034/src/audible_cli/cmds/cmd_download.py
    def get_audio(self, book: Book, target_dir: Path, quality: str = "best") -> Path | None:
        if quality not in AVAILABLE_AAXC_QUALITY:
            raise ValueError(f"invalid aaxc quality {quality}. options: {AVAILABLE_AAXC_QUALITY}")
        if not target_dir.is_dir():
            raise ValueError(f"target dir {target_dir} is not a directory")
        if not book.is_published():
            echo(f"Book {book.title} is not published yet.")
            return None
        if not book.is_downloadable:
            echo(f"Book {book.title} is not downloadable.")
            return None

        license_data = self.get_license(book, quality=quality)

        content_metadata = license_data["content_license"]["content_metadata"]
        url = content_metadata["content_url"]["offline_url"]
        codec: str = content_metadata["content_reference"]["content_format"]

        ext: str
        if codec.lower() == "mpeg":
            ext = "mp3"
        else:
            ext = "aaxc"

        audio_path = target_dir / f"{book.title}.{codec}.{ext}"
        voucher_path = audio_path.with_suffix(".voucher")

        if not voucher_path.exists():
            json_data = json.dumps(license_data, indent=4)
            with open(voucher_path, "w") as f:
                f.write(json_data)
        else:
            echo(f"Path {voucher_path} already exists. Skip download for voucher.")

        Downloader(
            url,
            audio_path,
            self.client.session,
            desc="audio",
            expected_types=["audio/aax", "audio/vnd.audible.aax", "audio/mpeg", "audio/x-m4a", "audio/audible"],
        ).run()

        return audio_path

    # Refs:
    # - https://github.com/mkb79/audible-cli/blob/b3adb9a33157322cd6d79ff59f5dacf06dc3e034/src/audible_cli/models.py#L346
    # - https://github.com/mkb79/Audible/issues/3
    def get_license(self, book: Book, quality: str = "best"):
        if quality not in AVAILABLE_AAXC_QUALITY:
            raise ValueError(f"invalid license quality {quality}. options: {AVAILABLE_AAXC_QUALITY}")

        body = {
            "supported_drm_types": ["Mpeg", "Adrm"],
            "quality": "High" if quality in ("best", "high") else "Normal",
            "consumption_type": "Download",
            "response_groups": "last_position_heard, pdf_url, content_reference",
        }
        headers = {
            "X-Amzn-RequestId": secrets.token_hex(20).upper(),
            "X-ADP-SW": "37801821",
            "X-ADP-Transport": "WIFI",
            "X-ADP-LTO": "120",
            "X-Device-Type-Id": "A2CZJZGLK2JJVM",
            "device_idiom": "phone",
        }

        data = self.client.post(
            f"content/{book.asin}/licenserequest",
            body=body,
            headers=headers,
        )

        content_license = data["content_license"]
        if content_license["status_code"] == "Denied":
            if "license_denial_reasons" in content_license:
                for reason in content_license["license_denial_reasons"]:
                    message = reason.get("message", "UNKNOWN")
                    rejection_reason = reason.get("rejectionReason", "UNKNOWN")
                    validation_type = reason.get("validationType", "UNKNOWN")
                    echo(
                        f"License denied message for {book.title}: {message}. "
                        f"Reason: {rejection_reason}."
                        f"Type: {validation_type}"
                    )
            msg = content_license["message"]
            raise Exception(f"failed to retrieve content license: {msg}")

        content_url = content_license["content_metadata"].get("content_url", {}).get("offline_url")
        if content_url is None:
            raise Exception("failed to retrieve download URL")

        if "license_response" in content_license:
            try:
                voucher = decrypt_voucher_from_licenserequest(self.client.auth, data)
            except Exception:
                echo(f"Failed to decrypt voucher for {book.title}")
            else:
                content_license["license_response"] = voucher
        else:
            echo(f"No voucher for {book.title} found")

        return data


def export(
    config: Config,
    target_dir: Path,
    renew: bool,
):
    """
    Export Audible data
    """
    auth = load_authenticator(config)
    audible_client = audible.Client(auth)
    client = Client(audible_client)

    index_file_path = target_dir.joinpath(EXPORT_INDEX_FILE_NAME)
    export_index = ExportIndex.load_or_default(index_file_path)

    book_library = client.get_books()
    for book in book_library:
        if export_index.check_book(book, skip_check=renew):
            chapters = client.get_chapters(book)
            annotation_version, annotations = client.get_annotations(book)

            # Note that we will generate the book name using its title and use the ".md" extension since it is
            # a Markdown file.
            book_path = target_dir / f"{book.title}.md"

            export_to_markdown(
                book_path,
                book,
                chapters=chapters,
                annotations=annotations,
                annotations_version=annotation_version,
            )

            if book.pdf_url:
                client.get_pdf(book, target_dir)

            # Print some info only if all books are expected to be exported.
            # We won't print anything otherwise as there was already a prompt
            # to confirm whether the book should be exported.
            if renew:
                echo(f"Exported book: {book}")

    # Log warning(s) for book(s) that are left unchecked.
    if not renew:
        export_index.warn_unchecked_books()

    # Save back the index
    export_index.save(index_file_path)

    # Close after completing the export
    client.close()


def download(
    config: Config,
    target_dir: Path,
):
    """
    Download audiobook file.
    """
    auth = load_authenticator(config)
    audible_client = audible.Client(auth)
    client = Client(audible_client)

    index_file_path = target_dir.joinpath(EXPORT_INDEX_FILE_NAME)
    export_index = ExportIndex.load_or_default(index_file_path)

    if len(export_index.books) == 0:
        echo("No books available for download. Have you used 'ncli audible export'?")
        return

    echo("List of available books:")
    for idx, item in enumerate(export_index.books):
        download_meta = ""
        if item.is_downloaded:
            download_meta = " (downloaded)"
        elif not item.info.is_downloadable:
            download_meta = " (not downloadable)"
        echo(f"{idx+1:3d}. {item.info.title}{download_meta}")
    echo("")
    idx = prompt_user_num("Which book do you want to download?", len(export_index.books))

    # Note that we need to use 0-based for indexing.
    selected_item = export_index.books[idx - 1]

    # Disallow choosing non-downloadable book.
    if not selected_item.info.is_downloadable:
        echo(f"Unable to download book {selected_item.info.title}")
        return

    audio_dir = target_dir / "audio"
    if not audio_dir.exists():
        audio_dir.mkdir()
    elif not audio_dir.is_dir():
        raise Exception(f"Path {audio_dir} must be a directory.")

    book_audio_dir = audio_dir / selected_item.info.title
    if not book_audio_dir.exists():
        book_audio_dir.mkdir()
    elif not book_audio_dir.is_dir():
        raise Exception(f"Path {book_audio_dir} must be a directory.")

    cover_path = client.get_cover(selected_item.info, book_audio_dir)
    audio_path = client.get_audio(selected_item.info, book_audio_dir)

    selected_item.is_downloaded = True
    export_index.save(index_file_path)

    try:
        if audio_path.suffix == ".aaxc":
            converter = AudioConverter(verbose=True)
            mp3_path = book_audio_dir / f"{selected_item.info.title}.mp3"

            echo("Coverting AAXC to MP3")
            converter.convert_aaxc_to_mp3(audio_path, mp3_path, cover_path=cover_path)
        elif audio_path.suffix == ".mp3":
            mp3_path = audio_path
        else:
            raise Exception(f"Unexpected extension for audio path: {audio_path}")

        echo("Splitting MP3 by chapters")
        chapters = client.get_chapters(selected_item.info)
        converter.split_mp3_by_chapters(
            mp3_path,
            chapters,
            cover_path=cover_path,
        )
    except ffmpeg.Error as e:
        # Print the captured stdout and stderr to help with debugging.
        print("Found error from ffmpeg:")
        print("stdout:", e.stdout.decode("utf8"))
        print("stderr:", e.stderr.decode("utf8"))
        raise e

    client.close()


# Refs:
# - https://github.com/KrumpetPirate/AAXtoMP3
class AudioConverter:
    def __init__(self, verbose: bool = False):
        """Initialize the converter."""
        self.verbose = verbose

    def convert_aaxc_to_mp3(
        self,
        aaxc_path: Path,
        mp3_path: Path,
        cover_path: Path | None,
    ):
        """Converts the given AAXC file into an MP3 file."""
        if aaxc_path.suffix != ".aaxc":
            raise ValueError(f"aaxc_path {aaxc_path} does not have '.aaxc' suffix.")
        elif not aaxc_path.exists():
            raise ValueError(f"Path {aaxc_path} does not exist.")
        if mp3_path.suffix != ".mp3":
            raise ValueError(f"mp3_path {mp3_path} does not have '.mp3' suffix.")
        elif mp3_path.exists():
            # TODO: How to handle if the `mp3_path` was only partially written?
            echo(f"Path {mp3_path} already exists. Skipping conversion from AAXC.")
            return

        # By convention, we assume that the AAXC voucher is always located
        # next to the AAXC file with a slightly different extension.
        voucher_path = aaxc_path.with_suffix(".voucher")
        if not voucher_path.exists():
            raise Exception(f"Path {voucher_path} does not exist.")
        with open(voucher_path) as f:
            voucher_data = json.load(f)
        key = voucher_data["content_license"]["license_response"]["key"]
        iv = voucher_data["content_license"]["license_response"]["iv"]

        acodec_options = {"audible_key": key, "audible_iv": iv}

        total_duration, metadata = self._probe_metadata(aaxc_path, **acodec_options)
        # Override the title since the original usually also includes subtitle.
        metadata["title"] = mp3_path.stem

        audio_stream = ffmpeg.input(str(aaxc_path), **acodec_options)

        output_kwargs = dict(
            acodec="libmp3lame",
            ab=AUDIO_BITRATE,  # Adjust bitrate as needed
            map_metadata=-1,  # Clear existing metadata
            loglevel="quiet",
            stats=None,
            **self._format_metadata(metadata),
        )
        if cover_path and cover_path.exists():
            cover_stream = ffmpeg.input(str(cover_path))
            stream = ffmpeg.output(
                audio_stream["a"],
                cover_stream["v"],
                str(mp3_path),
                **output_kwargs,
            )
        else:
            stream = ffmpeg.output(
                audio_stream,
                str(mp3_path),
                **output_kwargs,
            )

        with ProgressFfmpeg(total_duration) as progress:
            ffmpeg.run(
                stream.global_args("-progress", progress.output_file.name),
                capture_stdout=True,
                capture_stderr=True,
            )

    def split_mp3_by_chapters(
        self,
        mp3_path: Path,
        chapters: list[Chapter],
        chapter_name_prefix: str | None = None,
        cover_path: Path | None = None,
        metadata: dict | None = None,
    ):
        if len(chapters) == 0:
            return
        if mp3_path.suffix != ".mp3":
            raise ValueError(f"mp3_path {mp3_path} does not have '.mp3' suffix.")
        elif not mp3_path.exists():
            raise ValueError(f"Path {mp3_path} does not exist.")

        if not chapter_name_prefix:
            chapter_name_prefix = " - "
        else:
            # Add dot so that we can easily append the current (sub)chapter
            # index later.
            chapter_name_prefix = f"{chapter_name_prefix}."

        if metadata is None:
            _, metadata = self._probe_metadata(mp3_path)

        max_idx_digits = len(str(len(chapters)))
        for idx, chapter in enumerate(chapters):
            if chapter.start_ms is None or chapter.end_ms is None or chapter.start_ms >= chapter.end_ms:
                raise ValueError(
                    f"Chapter {chapter.title} has invalid start ({chapter.start_ms}) or end ({chapter.end_ms}).",
                )

            # If there are subchapters, we may need to modify the prefix
            # a little bit to get around the ordering used by some file system.
            has_subchapters = chapter.subchapters and len(chapter.subchapters) > 0
            ext_prefix = ""
            if has_subchapters:
                subchapters_max_idx_digits = len(str(len(chapter.subchapters)))
                ext_prefix = f".{0:0{subchapters_max_idx_digits}d}"

            ch_name_prefix = f"{chapter_name_prefix}{idx+1:0{max_idx_digits}d}"
            ch_name = f"{ch_name_prefix}{ext_prefix} - {chapter.title}"
            echo(f"Processing chapter {ch_name}")

            track_name = mp3_path.stem + ch_name
            ch_audio_path = mp3_path.with_stem(track_name)

            if not ch_audio_path.exists():
                ch_audio_stream = ffmpeg.input(
                    str(mp3_path),
                    # covert time unit to seconds
                    ss=chapter.start_ms / 1000,
                    t=(chapter.end_ms - chapter.start_ms) / 1000,
                )

                ch_metadata = metadata.copy()
                # Override the title to better match the (per-chapter) file name.
                ch_metadata["title"] = ch_audio_path.stem

                ch_output_kwargs = dict(
                    acodec="copy",  # Just copy audio, no re-encoding
                    map_metadata=-1,  # Clear existing metadata
                    **self._format_metadata(ch_metadata),
                )
                if cover_path and cover_path.exists():
                    cover_stream = ffmpeg.input(str(cover_path))
                    stream = ffmpeg.output(
                        ch_audio_stream["a"],
                        cover_stream["v"],
                        str(ch_audio_path),
                        **ch_output_kwargs,
                    )
                else:
                    stream = ffmpeg.output(
                        ch_audio_stream,
                        str(ch_audio_path),
                        **ch_output_kwargs,
                    )

                # It's fine to not use any progress bar here since it should be
                # quite fast (given that we don't do any re-encoding).
                stream.overwrite_output().run(
                    quiet=not self.verbose,
                    capture_stdout=True,
                    capture_stderr=True,
                )
            else:
                echo(f"Path {ch_audio_path} already exists. Skipping chapter conversion.")

            if has_subchapters:
                self.split_mp3_by_chapters(
                    mp3_path,
                    chapter.subchapters,
                    chapter_name_prefix=ch_name_prefix,
                    cover_path=cover_path,
                    metadata=metadata,
                )

    def _probe_metadata(self, audio_path: Path, **probe_kwargs: dict) -> tuple[float, dict[str, Any]]:
        probe = ffmpeg.probe(
            str(audio_path),
            **probe_kwargs,
        )

        total_duration = float(probe["format"].get("duration", 0))

        tags = probe["format"].get("tags", {})
        metadata = {
            "title": tags.get("title", ""),
            "artist": tags.get("artist", ""),
            # We don't export album here since somehow it can be mistaken
            # as the expected title on some platforms like Snipd.
            # "album": metadata.get("album", ""),
            "date": tags.get("date", ""),
            "genre": tags.get("genre", ""),
            "copyright": tags.get("copyright", ""),
            "publisher": tags.get("publisher", ""),
            "narrator": tags.get("composer", ""),
        }

        return (total_duration, metadata)

    def _format_metadata(self, metadata: dict) -> dict:
        """Format metadata for ffmpeg output with g:N format."""
        formatted = {}
        idx = 0
        for key, value in metadata.items():
            if value and str(value).strip():
                formatted[f"metadata:g:{idx}"] = f"{key}={value!r}"
                idx += 1
        return formatted
