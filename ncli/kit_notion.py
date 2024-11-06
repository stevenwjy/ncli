"""
A module for processing and managing Notion data.

This module provides functions and utilities for handling Notion data, including
exporting, converting, and organizing Notion content.
"""

import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import chardet
import pandas
import yaml
from click import echo
from pydantic import BaseModel, Field  # pylint: disable=no-name-in-module

from ncli.utils import prompt_user


TMP_DIR = f"{tempfile.gettempdir()}/ncli"
INDEX_FILE_NAME = "index.yaml"

# We assume all page files are formatted in UTF-8.
PAGE_FILE_ENCODING = "utf-8"

UUID_36_PATTERN = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
UUID_32_PATTERN = r"([0-9a-f]{32})"

# Upon exporting all workspace content from Notion, typically it will give a download link for a zip
# file that contains multiple parts, each in its own zip file.
EXPORT_FULL_NAME_RE = re.compile(rf"^{UUID_36_PATTERN}_Export-{UUID_36_PATTERN}\.zip$")
EXPORT_PART_NAME_RE = re.compile(rf"^Export-{UUID_36_PATTERN}-Part-[0-9]+\.zip$")

# Name of export item, except assets (e.g., images).
EXPORT_ITEM_NAME_RE = re.compile(rf"^(.*) {UUID_32_PATTERN}(_all)?(?:\.(md|csv))?$")

DATABASE_ID_COLUMN_NAME = "ID"
DATABASE_ID_RE = re.compile(r"^([A-Z][A-Z0-9\-]*-)?[0-9]+$")
DATABASE_ID_SEPARATOR_CHAR = "."

# Basically, a link item must either start with "[...](" or " (", which signifies the beginning of a markdown link,
# or "/", which signifies a separation with the previous directory.
#
# The name should not contain any several types of char (e.g., slash, newline, null).
# And the name should be followed by information about the uid of the entry according to Notion's naming convention.
LINK_ITEM_NAME_RE = re.compile(r"(\[.+\]\(| \(|\/)([^/\n\0]+)%20([0-9a-f]{32})")

ASSET_IMAGE_LINK_RE = re.compile(r"\!\[[^\n\0]+\]\([^\n\0]+\)")

# Note that this is length before extra prefix (e.g., database id) and suffix (e.g., because of duplicate names).
MAX_PAGE_NAME_LENGTH = 128


def export(
    source: Path,
    target: Path,
    force: bool,
) -> None:
    """
    Performs the export operation.

    Args:
        source (Path): The path to the source zip file.
        target (Path): The path to the target directory for the export.
        force (bool): A flag to indicate whether to overwrite the target directory if it exists.

    Returns:
        None, raises exceptions in case of errors.
    """
    root_dir = Directory()
    export_uid, export_dir, exported_data_dir = _validate_source(source)
    _build_directory_info(root_dir, exported_data_dir)

    # Create mapping of entries by their uid. This is to help with linking later.
    # This will also set up name_suffix on each entry if needed (for name dedup in the same directory).
    entries_by_uid: dict[str, Entry] = {}
    _build_entries_map_by_uid(entries_by_uid, root_dir)

    if target.exists():
        if not force and not prompt_user(
            f"Target path '{target}' already exists. Delete current data?"
        ):
            echo("Cancelling export since target path already exists.")
            return

        echo(f"Removing '{target}' ...")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            os.remove(target)

    echo(f"Exporting data to '{target}' ...")
    os.makedirs(target, exist_ok=True)
    _build_target_directory(target, export_uid, root_dir, entries_by_uid)

    # Clean up the tmp directory
    shutil.rmtree(export_dir)

    echo("Export operation has been executed successfully")


def _validate_source(path: Path) -> tuple[str, Path, Path]:
    """
    Validates the source zip file and extracts it to a temporary directory.

    Returns:
      - Unique id for the export.
      - Path to the entire tmp directory (for further clean up)
      - Path to the exported notion data (after extracting all zip parts)
    """
    if not path.exists():
        raise ValueError("Source path does not exist")
    if not EXPORT_FULL_NAME_RE.match(path.name):
        raise ValueError("Invalid export file name")

    # Prepare the export directory
    date_string = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    export_dir = Path(TMP_DIR).joinpath(f"notion-export-{date_string}")
    if export_dir.exists():
        if export_dir.is_dir():
            echo(f"Removing dir '{export_dir}' to avoid conflict")
            shutil.rmtree(export_dir)
        else:
            echo(f"Removing file '{export_dir}' to avoid conflict")
            os.remove(export_dir)
    os.makedirs(export_dir, exist_ok=True)

    with zipfile.ZipFile(path, "r") as zip_ref:
        zip_ref.extractall(export_dir)

    part_zip_files: list[Path] = []
    for part_zip_file in export_dir.iterdir():
        if not part_zip_file.is_file() or not part_zip_file.name.endswith(".zip"):
            raise ValueError(f"found unexpected non-zip file: {part_zip_file}")
        part_zip_files.append(part_zip_file)
    if len(part_zip_files) == 0:
        raise ValueError("unable to find any export part zip file")

    export_uid = None
    for path in part_zip_files:
        match = EXPORT_PART_NAME_RE.match(path.name)
        if not match:
            raise ValueError(f"part zip file does not match name format: {path}")

        echo(f"Extracting: {path.name}")

        # Sanity check for consistency.
        uid = match.group(1)
        if export_uid is not None and export_uid != uid:
            raise ValueError(
                f"inconsistent export uid. prev: {export_uid}. cur: {uid}."
            )
        export_uid = uid

        with zipfile.ZipFile(path, "r") as zip_ref:
            zip_ref.extractall(export_dir)

    exported_data_dir = export_dir.joinpath(f"Export-{export_uid}")
    if not exported_data_dir.exists():
        raise ValueError(f"Unexpected: exported dir {exported_data_dir} does not exist")

    # Rename to follow semantic with other files
    export_uid = export_uid.replace("-", "")
    expected_export_data_dir = export_dir.joinpath(
        f"Export {export_uid.replace('-', '')}"
    )
    os.rename(exported_data_dir, expected_export_data_dir)

    return export_uid, export_dir, expected_export_data_dir


class Entry:
    """
    A class representing an entry in the export directory structure.

    NOTE: This is an abstract class.
    """

    uid: str
    name: str
    path: Path

    # Optional field that is used if the file name generated by Notion is not equal to `name`.
    #
    # Example: for Markdown page, we prefer to use the actual heading as name instead of the sanitized
    # name generated by Notion.
    name_ori: str | None

    # Extra suffix to the name in case there are multiple entries with the same name in a single directory.
    # For example, we may add suffix like " (2)", " (3)", etc.
    #
    # This is typically only used if there are multiple pages or databases with the same name in a single directory.
    # The suffix is currently determined by the lexicographical order of uids, which is not timestamp-ordered.
    #
    # It is recommended to not have any duplicate entry names within the same directory, except for database
    # pages that have ID column (since the file name will be prefixed with their unique ID).
    name_suffix: str | None

    def __init__(
        self, uid: str, name: str, path: Path, name_ori=None, name_suffix=None
    ):
        self.uid = uid

        self.name = name
        self.name_ori = name_ori
        self.name_suffix = name_suffix

        self.path = path

    def get_name_ori(self):
        if self.name_ori:
            return self.name_ori
        else:
            return self.name

    def get_exported_name(self) -> str:
        """
        Returns exported name. Note that this does NOT include any extension.
        """
        # Whitespace at the end of the name (before extension) may not work well on some
        # system or app (e.g., Obsidian).
        #
        # Also, we will remove unexpected characters like slash and null char.
        exported_name = self.name.strip()

        # Non-printable char: \0
        # Forbidden in Unix: /
        # Forbidden in Markdown/Obsidian linking: #, ^, [, ], |
        # Forbidden by Obsidian: \, :
        #
        # Note that Windows could have more forbidden chars and reserved words.
        # Reference: https://en.wikipedia.org/wiki/Filename

        exported_name = re.sub(r"[\0#^]", "", exported_name)
        exported_name = re.sub(r"\/", " or ", exported_name)
        exported_name = re.sub(r"\[", "- ", exported_name)
        exported_name = re.sub(r"[\]:]", " -", exported_name)
        exported_name = re.sub(r"\|", "-", exported_name)

        # Replace multiple whitespaces with a single whitespace
        exported_name = re.sub(r"\s+", " ", exported_name)

        # Note that the actual file name may still have extra prefix (if there's any database ID)
        # and suffix (if there's duplicate name in the directory).
        if len(exported_name) > MAX_PAGE_NAME_LENGTH:
            exported_name = exported_name[:MAX_PAGE_NAME_LENGTH]

        # Since we set the name suffix here, we assume that it's already safe.
        if self.name_suffix:
            exported_name += self.name_suffix

        return exported_name


class Asset:
    """
    An asset file.
    """

    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path

    def get_exported_name(self) -> str:
        """
        Returns exported name.
        """
        return self.name


class Directory:
    """
    A directory entry containing a version and a list of child entries.
    """

    def __init__(self):
        self._entries_by_uid: dict[str, Entry] = {}
        self.assets: list[Asset] = []

    def add_entry(self, entry: Entry):
        self._entries_by_uid[entry.uid] = entry

    def get_entry_by_uid(self, uid: str) -> Entry | None:
        return self._entries_by_uid.get(uid)

    def sorted_entry_uids(self):
        return sorted(list(self._entries_by_uid.keys()))

    def add_asset(self, asset: Asset):
        self.assets.append(asset)


class Page(Entry):
    """
    A page entry.
    """

    subdir: Directory | None

    def __init__(
        self,
        uid: str,
        name: str,
        path: Path,
        name_ori: str | None,
        subdir: Directory | None = None,
    ):
        super().__init__(uid, name, path, name_ori=name_ori)
        self.subdir = subdir


class DatabaseView(Entry):
    """
    An entry representing a database view (CSV).
    """

    subdir: Directory | None

    # Special property that indicates whether this is the full view of the database (without filter and sort).
    is_all: bool

    # The following fields related to id is only valid if `is_all` is True.
    #
    # `has_id_column` indicates whether the database has a unique id column.
    # If `has_id_column`` is true, `id_prefix` indicates whether the id has a certain prefix.
    #
    # If the ID looks like "XYZ-123" in Notion, the value of `id_prefix` will be "XYZ-"
    # (note that there is a dash suffix).
    has_id_column: bool
    id_prefix: str | None

    def __init__(
        self,
        uid: str,
        name: str,
        path: Path,
        is_all: bool = False,
        has_id_column: bool = False,
        id_prefix: str | None = None,
        subdir: Directory | None = None,
    ):
        super().__init__(uid, name, path)
        self.subdir = subdir
        self.is_all = is_all
        self.has_id_column = has_id_column
        self.id_prefix = id_prefix


class DatabasePage(Entry):
    """
    A database page entry.
    """

    subdir: Directory | None

    db_id: str | None

    def __init__(
        self,
        uid: str,
        name: str,
        path: Path,
        name_ori: str | None = None,
        db_id: str | None = None,
        subdir: Directory | None = None,
    ):
        super().__init__(uid, name, path, name_ori=name_ori)
        self.db_id = db_id
        self.subdir = subdir

    # Override. Note that this does NOT include any file extension.
    def get_exported_name(self):
        if self.db_id:
            return f"{self.db_id}{DATABASE_ID_SEPARATOR_CHAR} {super().get_exported_name()}"
        else:
            return super().get_exported_name()


def _build_directory_info(
    directory: Directory, path: Path, parent_database: DatabaseView | None = None
):
    if not path.is_dir():
        raise ValueError(
            "unexpected: _build_directory_info is called with non-directory path"
        )

    # Tuple of uid, name, and path to a directory.
    subdirs: list[tuple[str, str, Path]] = []

    for child in path.iterdir():
        match = EXPORT_ITEM_NAME_RE.match(child.name)

        if not match:
            directory.add_asset(Asset(name=child.name, path=child))
            continue

        name = match.group(1)
        uid = match.group(2)
        is_all = match.group(3)
        extension = match.group(4)

        if not extension:
            subdirs.append((uid, name, child))
            continue

        if extension == "md":
            # We will replace the name based on the actual file heading here.
            # This is because sometimes Notion limits the file name to 50 chars.
            #
            # We will clean up unexpected chars (e.g., "/") and do trimming if necessary in `get_exported_name`.
            name_ori = name
            name = _find_heading_from_md_page(child)

            if not parent_database or not parent_database.has_id_column:
                if not parent_database:
                    directory.add_entry(
                        Page(uid=uid, name=name, path=child, name_ori=name_ori)
                    )
                else:
                    directory.add_entry(
                        DatabasePage(uid=uid, name=name, path=child, name_ori=name_ori)
                    )
            else:
                # If the parent database has an id column, we need to check what ID this file correlates to.
                # Because there's no uid on the CSV file and there may be multiple rows that have the same
                # title (name).

                db_page_id = _find_database_id_from_md(child, parent_database.id_prefix)
                if db_page_id is None:
                    raise ValueError(
                        f"Unable to find db id with prefix '{parent_database.id_prefix}' on file '{child}'."
                    )

                directory.add_entry(
                    DatabasePage(
                        uid=uid,
                        name=name,
                        path=child,
                        name_ori=name_ori,
                        db_id=db_page_id,
                    )
                )

        elif extension == "csv":
            existing_entry = directory.get_entry_by_uid(uid)

            # Somehow Notion can produce two CSV files on the database location.
            # If that's the case, prefer the one with `_all.csv` suffix.
            if existing_entry is None or is_all:
                if not is_all:
                    directory.add_entry(DatabaseView(uid=uid, name=name, path=child))
                else:
                    has_id_column, id_prefix = _find_database_id_info_from_csv(child)
                    directory.add_entry(
                        DatabaseView(
                            uid=uid,
                            name=name,
                            path=child,
                            is_all=True,
                            has_id_column=has_id_column,
                            id_prefix=id_prefix,
                        )
                    )
        else:
            raise ValueError(f"unexpected file extension: {extension}")

    for uid, name, path in subdirs:
        entry = directory.get_entry_by_uid(uid)
        if entry is None:
            raise ValueError(f"unable to find entry for directory with path: {path}")
        if name != entry.get_name_ori():
            raise ValueError(
                f"Directory '{path}' name '{name}' does not match entry name '{entry.name}'."
            )

        subdir = Directory()
        if isinstance(entry, DatabaseView):
            _build_directory_info(subdir, path, parent_database=entry)
        else:
            _build_directory_info(subdir, path)

        entry.subdir = subdir


def _find_heading_from_md_page(path: Path) -> str | None:
    heading = open(path, encoding=PAGE_FILE_ENCODING).readline().rstrip()

    if not heading.startswith("# "):
        raise ValueError(
            f"failed to find page heading from '{path}', first line: '{heading}'"
        )

    # Remove the "# " prefix
    heading = heading[2:]
    return heading


def _find_database_id_info_from_csv(path: Path) -> tuple[bool, str | None]:
    """
    Finds information about the ID column in the database, if any.

    A valid ID column must satisfy the following properties:
    - The column name is 'ID'. At the moment, this is not configurable.
    - All values are non-empty.
    - It must follow the defined regex, which is based on the rules in the Notion app.

    Note that even if there's a column named 'ID', if it does not satisfy any of the other
    properties, we will just assume it's not a valid id column. This is to handle the case
    where someone uses such column name but is not of type 'ID' in Notion.
    """
    df = pandas.read_csv(path)

    # Check whether there's an ID column.
    if DATABASE_ID_COLUMN_NAME not in df.columns:
        return (False, None)

    # Check whether the values are convertible to string.
    # If error (e.g., because the value is None), it won't be considered as a valid ID column.
    try:
        id_col_values = df[DATABASE_ID_COLUMN_NAME].astype(str)
    except KeyError:
        return (False, None)

    # If the database is empty, no need for this checking.
    if len(id_col_values) == 0:
        return (False, None)

    # Check whether all values in the ID column conforms to the pattern.
    if not id_col_values.apply(lambda x: bool(DATABASE_ID_RE.match(str(x)))).all():
        return (False, None)

    # Use the first row to find the prefix
    match = DATABASE_ID_RE.match(str(id_col_values[0]))
    prefix = match.group(1)

    return (True, prefix)


def _find_database_id_from_md(path: Path, id_prefix: str | None) -> str | None:
    column_prefix = f"{DATABASE_ID_COLUMN_NAME}: "

    # Sharper expected prefix if there's any id_prefix
    expected_prefix = column_prefix
    if id_prefix:
        expected_prefix += id_prefix

    with open(path, encoding="utf8") as file:
        line_count = 0
        for line in file:
            line_count += 1

            if line_count == 1:
                if not line.startswith("# "):
                    raise ValueError("markdown file does not start with heading")
            elif line_count == 2:
                if line.strip() != "":
                    raise ValueError(
                        "markdown file does not have newline after heading"
                    )
            else:
                # Ignore fields with different value
                if not line.startswith(expected_prefix):
                    continue

                # Remove the 'ID: ' prefix, and strip unnecessary whitespaces.
                id_str = line[len(column_prefix) :].strip()

                if DATABASE_ID_RE.match(id_str):
                    return id_str
                else:
                    echo(f"WARN: ignored db id candidate '{id_str}'")

    return None


def _build_entries_map_by_uid(entries_map: dict[str, Entry], directory: Directory):
    # To help deduplicate names (except for database page which will be prefixed by unique ID)
    name_counts: dict[str, int] = {}

    for uid in directory.sorted_entry_uids():
        entry = directory.get_entry_by_uid(uid)
        existing_entry = entries_map.get(uid)
        if existing_entry:
            raise ValueError(
                f"found two entries with the same uid: '{existing_entry.path}', '{entry.path}'"
            )

        entries_map[uid] = entry

        if isinstance(entry, (Page, DatabasePage, DatabaseView)):
            if entry.subdir:
                _build_entries_map_by_uid(entries_map, entry.subdir)
        else:
            raise ValueError(f"unknown entry type: {entry}")

        # The db_id should have been unique.
        if isinstance(entry, DatabasePage) and entry.db_id is not None:
            continue

        # Best effort name deduplication. Note that we iterate based on uid, which is not timestamp-ordered here.
        # Hence it may not be stable in case there are new entries added with the same name.
        count = name_counts.get(entry.name, 0)
        if count > 0:
            entry.name_suffix = f" ({count})"
        name_counts[entry.name] = count + 1


def _detect_file_encoding(file_path):
    with open(file_path, "rb") as f:
        result = chardet.detect(f.read())
    return result["encoding"]


def _update_md_file_heading(file_path: Path, heading: str):
    with open(file_path, encoding=PAGE_FILE_ENCODING) as file:
        lines = file.readlines()

    lines[0] = f"# {heading}\n"

    with open(file_path, "w", encoding=PAGE_FILE_ENCODING) as file:
        file.writelines(lines)


def _update_links_on_file(file_path: Path, entries_by_uid: dict[str, Entry]):
    # Somehow exported files from Notion could have encodings such as 'ascii', 'Windows-1252', and 'Windows-1254'.
    # However, if we use such encoding to read the file, sometimes there could be errors.
    # Hence, we will just print some warnings here if we are about to change the encoding.
    enc = _detect_file_encoding(file_path)
    target_enc = PAGE_FILE_ENCODING
    if enc != target_enc:
        # The warning is commented out because this can be a bit too noisy.
        # Should probably be fine to change the encoding.
        pass
        # echo(f"WARN: Changing file {file_path} encofing from {enc} to {target_enc}")

    with open(file_path, encoding=target_enc) as file:
        data = file.read()

    def replacement(m: re.Match) -> str:
        # This prefix is usually to avoid unexpected match, e.g., making sure it starts with certain
        # patterns as documented around the regex definition.
        prefix = m.group(1)
        name = m.group(2)
        uid = m.group(3)

        entry = entries_by_uid.get(uid)
        if entry is None:
            # If the entry could not be found, just return the name back (i.e., trim the uid).
            #
            # This could somehow happen when a page links to a specific database view. Given that
            # Notion typically only exports either "current view" or "default view", the linked
            # view may not get exported.
            #
            # In such scenario, this link could still end up working, but it would point to the
            # exported view instead of the view recorded in Notion.
            echo(
                f"WARN: found link to entry with non-existent uid {uid} (name: {name}) in file '{file_path}'."
            )
            return prefix + name

        # Sanity check for name consistency.
        # Note that in a Markdown link we must use "%20" instead of whitespace.
        if name != entry.get_name_ori().replace(" ", "%20"):
            raise ValueError(
                f"found inconsistent name for entry {uid} in file '{file_path}', "
                f"expected name: '{entry.name}', found: '{name}'."
            )
        exported_name = entry.get_exported_name().replace(" ", "%20")

        return prefix + exported_name

    # Fix the link, basically for each uid find if it should be replaced to empty string or a certain name suffix.
    data = LINK_ITEM_NAME_RE.sub(replacement, data)

    # Write the data back to the file
    with open(file_path, "w", encoding=target_enc) as file:
        file.write(data)


def _build_target_directory(
    path: Path,
    uid: str,
    directory: Directory,
    # To help with fixing links. This contains entries across all export data,
    # not only this directory.
    entries_by_uid: dict[str, Entry],
) -> None:
    """
    Builds the target directory structure.
    """
    index_dir = IndexDir(uid=uid)

    # Guaranteed to be unique by the export format.
    for asset in directory.assets:
        exported_name = asset.get_exported_name()

        index_dir.assets.append(IndexItemAsset(name=exported_name))

        # Move from the tmp dir to the target dir
        shutil.copy(asset.path, path.joinpath(exported_name))

    for entry_uid in directory.sorted_entry_uids():
        entry = directory.get_entry_by_uid(entry_uid)

        # TODO: Handle more restrictive file name format on Windows
        exported_name = entry.get_exported_name()

        if isinstance(entry, (Page, DatabasePage)):
            target_path = path.joinpath(exported_name + ".md")
            index_dir.pages.append(IndexItemPage(name=target_path.name, uid=entry.uid))

            shutil.copy(entry.path, target_path)
            _update_links_on_file(target_path, entries_by_uid)

            # If it's a database page with an id, we want the heading to have ID prefix like the file name.
            if isinstance(entry, DatabasePage) and entry.db_id:
                # Note that this updated heading may not be equal to the file name, since the file name may
                # be trimmed if exceeding certain length and have unexpected chars (e.g., "/") removed.
                _update_md_file_heading(
                    target_path,
                    f"{entry.db_id}{DATABASE_ID_SEPARATOR_CHAR} {entry.name}",
                )

        elif isinstance(entry, DatabaseView):
            target_path = path.joinpath(exported_name + ".csv")
            index_dir.pages.append(
                IndexItemDatabase(name=target_path.name, uid=entry.uid)
            )

            shutil.copy(entry.path, target_path)
        else:
            raise ValueError(f"unknown entry type: {entry}")

        if entry.subdir:
            target_path = path.joinpath(exported_name)
            os.makedirs(target_path, exist_ok=True)
            _build_target_directory(
                target_path, entry.uid, entry.subdir, entries_by_uid
            )

    # Write the index file.
    index_file = path.joinpath(INDEX_FILE_NAME)
    index_str = yaml.dump(index_dir.dict())
    with open(index_file, "w", encoding=PAGE_FILE_ENCODING) as file:
        file.write(index_str)


class IndexItemPage(BaseModel):
    """
    Index representation for a page file (Markdown).
    """

    uid: str
    name: str


class IndexItemDatabase(BaseModel):
    """
    Index representation for a database file (CSV).
    """

    uid: str
    name: str


class IndexItemAsset(BaseModel):
    """
    Index representation for an asset file.
    """

    name: str


class IndexDir(BaseModel):
    """
    Index representation for a directory.
    """

    uid: str

    assets: list[IndexItemAsset] = Field(default_factory=list)
    databases: list[IndexItemDatabase] = Field(default_factory=list)
    pages: list[IndexItemPage] = Field(default_factory=list)
