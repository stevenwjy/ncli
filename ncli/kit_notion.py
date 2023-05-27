"""
A module for processing and managing Notion data.

This module provides functions and utilities for handling Notion data, including
exporting, converting, and organizing Notion content.
"""

import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Union

import chardet
from click import echo

TMP_DIR = "/tmp/ncli"
VERSION_FILE_NAME = "version.txt"
EXPORT_NAME_RE = re.compile(
    r"^Export-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.zip$")
VERSIONED_NAME_RE = re.compile(r"^(.*) ([0-9a-f]{32})(?:\.(md|csv))?$")


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
    extracted_dir = _validate_source(source)
    entry = _build_entry(extracted_dir)

    if target.exists():
        if not force:
            raise ValueError(f"Target path '{target}' already exists")

        echo(
            f"Target path '{target}' already exists. Removing it since force option is used")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            os.remove(target)

    echo(f"Creating target directory: {target}")
    os.makedirs(target, exist_ok=True)

    echo("Building target directory")
    _build_target(target, entry)

    shutil.rmtree(extracted_dir)

    echo("Export operation has been executed successfully")


def _validate_source(path: Path) -> Path:
    """
    Validates the source zip file and extracts it to a temporary directory.

    Args:
        path (Path): The path to the source zip file.

    Returns:
        Path: the path to the extracted directory or an error. Raises exceptions in case of errors.
    """
    if not path.exists():
        raise ValueError("Source path does not exist")

    file_name = path.name
    match = EXPORT_NAME_RE.match(file_name)

    if not match:
        raise ValueError("Invalid export file name")

    date_string = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    export_dest = Path(TMP_DIR).joinpath(f"notion-export-{date_string}")

    if export_dest.exists():
        if export_dest.is_dir():
            echo(f"Removing dir '{export_dest}' to avoid conflict")
            shutil.rmtree(export_dest)
        else:
            echo(f"Removing file '{export_dest}' to avoid conflict")
            os.remove(export_dest)

    os.makedirs(export_dest, exist_ok=True)

    with zipfile.ZipFile(path, "r") as zip_ref:
        zip_ref.extractall(export_dest)

    exported_dir = file_name[:-4]  # remove '.zip'
    exported_dir = export_dest.joinpath(exported_dir)

    if not exported_dir.exists():
        raise ValueError(
            f"Unexpected: exported dir {exported_dir} does not exist")

    # Rename to follow semantic with other files
    export_version = match.group(1).replace("-", "")
    expected_export_dir = export_dest.joinpath(f"Export {export_version}")
    os.rename(exported_dir, expected_export_dir)

    return expected_export_dir


@dataclass
class Entry:
    """
    A class representing an entry in the export directory structure.

    Attributes:
        name (str): The name of the entry.
        path (Path): The path to the entry in the file system.
        kind (Union["Dir", "Page", "Asset"]): The type of the entry (e.g., Dir, Page, or Asset).
    """

    def __init__(
        self,
        name: str,
        path: Path,
        kind: Union["Dir", "Page", "Asset"],
    ) -> None:
        self.name = name
        self.path = path
        self.kind = kind


@dataclass
class Dir:
    """
    A directory entry containing a version and a list of child entries.

    Attributes:
        version (str): The version string of the directory.
        children (List[Entry]): A list of child entries in the directory.
    """

    def __init__(self, version: str, children: List[Entry]) -> None:
        self.version = version
        self.children = children


@dataclass
class Page:
    """
    A page entry containing a version and an extension.

    Attributes:
        version (str): The version string of the page.
        extension (str): The file extension of the page (e.g., 'md', 'csv').
    """

    def __init__(self, version: str, extension: str) -> None:
        self.version = version
        self.extension = extension


@dataclass
class Asset:
    """
    An asset entry representing non-versioned files.
    """


def _build_entry(path: Path) -> Entry:
    """
    Builds an Entry object from the given path.

    Args:
        path (Path): The path to the entry in the file system.

    Returns:
        Entry: The Entry object. Raises exceptions in case of errors.
    """
    file_name = path.name

    match = VERSIONED_NAME_RE.match(file_name)
    if match:
        name = match.group(1)
        version = match.group(2)

        if path.is_dir():
            children = [_build_entry(child) for child in path.iterdir()]
            return Entry(
                name=name,
                path=path,
                kind=Dir(version=version, children=children),
            )

        extension = match.group(3)
        return Entry(
            name=name,
            path=path,
            kind=Page(version=version, extension=extension),
        )

    return Entry(
        name=file_name,
        path=path,
        kind=Asset(),
    )


def _detect_file_encoding(file_path):
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
    return result['encoding']


def _remove_versions(file_path: Path):
    # Somehow exported files from Notion could have encodings such as 'ascii', 'Windows-1252', and 'Windows-1254'.
    # However, if we use such encoding to read the file, sometimes there could be errors.
    # Hence, we will just print some warnings here if we are about to change the encoding.
    enc = _detect_file_encoding(file_path)
    target_enc = 'utf-8'
    if enc != target_enc:
        echo(
            f'WARN: Changing file {file_path} encofing from {enc} to {target_enc}')

    with open(file_path, 'r', encoding=target_enc) as file:
        data = file.read()

    # Remove the pattern from the data
    data = re.sub('%20[0-9a-f]{32}', '', data)

    # Write the data back to the file
    with open(file_path, 'w', encoding=target_enc) as file:
        file.write(data)


def _build_target(path: Path, entry: Entry) -> None:
    """
    Builds the target directory structure based on the given Entry.

    Args:
        path (Path): The path to the target directory.
        entry (Entry): The root Entry object representing the directory structure.

    Returns:
        None, raises exceptions in case of errors.
    """
    if isinstance(entry.kind, Dir):
        version_file = path.joinpath(VERSION_FILE_NAME)

        with version_file.open("w") as f:
            f.write(f"version: {entry.kind.version}\n\n")
            f.write("Entries:\n")

            for child in entry.kind.children:
                if isinstance(child.kind, Page):
                    file_name = f"{child.name}.{child.kind.extension}"
                    target_path = path.joinpath(file_name)
                    shutil.copy(child.path, target_path)

                    # Remove versions from the file content (esp. hyperlinks), so that we could navigate properly.
                    _remove_versions(target_path)

                    f.write(
                        f"- '[Page] {file_name}': '{child.kind.version}'\n")

                elif isinstance(child.kind, Asset):
                    file_name = child.name
                    shutil.copy(child.path, path.joinpath(file_name))

                    f.write(f"- '[Asset] {file_name}'\n")

                elif isinstance(child.kind, Dir):
                    child_path = path.joinpath(child.name)
                    os.makedirs(child_path, exist_ok=True)
                    _build_target(child_path, child)

                    f.write(
                        f"- '[Dir] {child.name}': '{child.kind.version}'\n")

    else:
        raise ValueError("build_target must be called with a directory entry")
