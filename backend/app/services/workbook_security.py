from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Protocol
from unicodedata import normalize as unicode_normalize
from xml.etree import ElementTree


WORKBOOK_READ_ERROR = (
    "Workbook could not be read. Please upload a valid, non-password-protected Excel file."
)
_READ_CHUNK_SIZE = 64 * 1024
_RELATIONSHIP_TAG = "Relationship"
_END_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x05\x06"
_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
_END_CENTRAL_DIRECTORY_SIZE = 22
_MAX_ZIP_COMMENT_SIZE = 65_535
_CENTRAL_DIRECTORY_HEADER_SIZE = 46


class WorkbookSecurityError(ValueError):
    """Internal preflight failure whose details must never be returned to clients."""


class WorkbookSecuritySettings(Protocol):
    max_upload_size_bytes: int
    upload_archive_max_uncompressed_bytes: int
    upload_archive_max_entries: int
    upload_archive_max_entry_bytes: int
    upload_archive_max_compression_ratio: float


@dataclass(frozen=True, slots=True)
class WorkbookSecurityLimits:
    max_compressed_bytes: int
    max_uncompressed_bytes: int
    max_entries: int
    max_entry_bytes: int
    max_compression_ratio: float

    @classmethod
    def from_settings(
        cls,
        settings: WorkbookSecuritySettings,
    ) -> "WorkbookSecurityLimits":
        return cls(
            max_compressed_bytes=settings.max_upload_size_bytes,
            max_uncompressed_bytes=settings.upload_archive_max_uncompressed_bytes,
            max_entries=settings.upload_archive_max_entries,
            max_entry_bytes=settings.upload_archive_max_entry_bytes,
            max_compression_ratio=settings.upload_archive_max_compression_ratio,
        )

    def validate(self) -> None:
        if (
            self.max_compressed_bytes <= 0
            or self.max_uncompressed_bytes <= 0
            or self.max_entries <= 0
            or self.max_entry_bytes <= 0
            or self.max_compression_ratio <= 1
        ):
            raise WorkbookSecurityError("invalid workbook security limits")


@dataclass(frozen=True, slots=True)
class _CentralDirectory:
    entry_count: int
    start: int
    end: int


def _canonical_member_name(raw_name: str) -> str:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise WorkbookSecurityError("unsafe archive member name")

    normalised = unicode_normalize("NFC", raw_name)
    is_directory = normalised.endswith("/")
    path_text = normalised[:-1] if is_directory else normalised
    raw_parts = path_text.split("/")
    path = PurePosixPath(path_text)
    if path.is_absolute() or normalised.startswith("/"):
        raise WorkbookSecurityError("unsafe archive member path")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise WorkbookSecurityError("unsafe archive member path")
    if path.parts and ":" in path.parts[0]:
        raise WorkbookSecurityError("unsafe archive member path")
    return "/".join(path.parts).casefold()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(unix_mode) == stat.S_IFLNK


def _read_central_directory(
    file_bytes: bytes,
    *,
    limits: WorkbookSecurityLimits,
) -> _CentralDirectory:
    search_start = max(
        0,
        len(file_bytes) - _END_CENTRAL_DIRECTORY_SIZE - _MAX_ZIP_COMMENT_SIZE,
    )
    search_end = len(file_bytes)
    while True:
        offset = file_bytes.rfind(
            _END_CENTRAL_DIRECTORY_SIGNATURE,
            search_start,
            search_end,
        )
        if offset < 0:
            raise WorkbookSecurityError("missing ZIP central directory")
        if offset + _END_CENTRAL_DIRECTORY_SIZE <= len(file_bytes):
            comment_size = int.from_bytes(file_bytes[offset + 20 : offset + 22], "little")
            if offset + _END_CENTRAL_DIRECTORY_SIZE + comment_size == len(file_bytes):
                break
        search_end = offset

    disk_number = int.from_bytes(file_bytes[offset + 4 : offset + 6], "little")
    central_directory_disk = int.from_bytes(file_bytes[offset + 6 : offset + 8], "little")
    entries_on_disk = int.from_bytes(file_bytes[offset + 8 : offset + 10], "little")
    total_entries = int.from_bytes(file_bytes[offset + 10 : offset + 12], "little")
    central_directory_size = int.from_bytes(
        file_bytes[offset + 12 : offset + 16],
        "little",
    )
    central_directory_offset = int.from_bytes(
        file_bytes[offset + 16 : offset + 20],
        "little",
    )
    if disk_number or central_directory_disk or entries_on_disk != total_entries:
        raise WorkbookSecurityError("multi-disk ZIP archives are not permitted")
    # Configured XLSX limits are far below the ZIP64 sentinel. Rejecting the
    # sentinel before ZipFile construction prevents an oversized central
    # directory from being materialised merely to count it.
    if total_entries == 0xFFFF or not 0 < total_entries <= limits.max_entries:
        raise WorkbookSecurityError("archive entry count limit exceeded")
    if central_directory_size == 0xFFFFFFFF or central_directory_offset == 0xFFFFFFFF:
        raise WorkbookSecurityError("ZIP64 archives are not permitted")
    physical_start = offset - central_directory_size
    if physical_start < 0 or central_directory_offset > physical_start:
        raise WorkbookSecurityError("malformed ZIP central directory")
    return _CentralDirectory(
        entry_count=total_entries,
        start=physical_start,
        end=offset,
    )


def _validate_raw_central_directory_names(
    file_bytes: bytes,
    *,
    directory: _CentralDirectory,
) -> None:
    # On Windows, zipfile normalises a raw backslash to '/'. Inspect the bounded
    # central-directory records as well so an unsafe original spelling cannot
    # disappear before the platform-independent path checks run.
    offset = directory.start
    for _ in range(directory.entry_count):
        header_end = offset + _CENTRAL_DIRECTORY_HEADER_SIZE
        if (
            offset < 0
            or header_end > len(file_bytes)
            or file_bytes[offset : offset + 4] != _CENTRAL_DIRECTORY_SIGNATURE
        ):
            raise WorkbookSecurityError("malformed ZIP central directory")
        filename_size = int.from_bytes(file_bytes[offset + 28 : offset + 30], "little")
        extra_size = int.from_bytes(file_bytes[offset + 30 : offset + 32], "little")
        comment_size = int.from_bytes(file_bytes[offset + 32 : offset + 34], "little")
        record_end = header_end + filename_size + extra_size + comment_size
        if record_end > len(file_bytes):
            raise WorkbookSecurityError("malformed ZIP central directory")
        raw_name = file_bytes[header_end : header_end + filename_size]
        if not raw_name or b"\\" in raw_name or b"\x00" in raw_name:
            raise WorkbookSecurityError("unsafe archive member name")
        offset = record_end
    if offset != directory.end:
        raise WorkbookSecurityError("archive entry count mismatch")


def _validate_member_metadata(
    infos: list[zipfile.ZipInfo],
    *,
    limits: WorkbookSecurityLimits,
) -> None:
    if not infos or len(infos) > limits.max_entries:
        raise WorkbookSecurityError("archive entry count limit exceeded")

    seen_names: set[str] = set()
    total_size = 0
    for info in infos:
        canonical_name = _canonical_member_name(info.filename)
        if canonical_name in seen_names:
            raise WorkbookSecurityError("duplicate archive member")
        seen_names.add(canonical_name)

        if info.flag_bits & 0x1:
            raise WorkbookSecurityError("encrypted archive member")
        if _is_symlink(info):
            raise WorkbookSecurityError("symbolic-link archive member")
        if info.file_size < 0 or info.compress_size < 0:
            raise WorkbookSecurityError("invalid archive member size")
        if info.is_dir():
            continue
        if info.file_size > limits.max_entry_bytes:
            raise WorkbookSecurityError("archive member size limit exceeded")

        total_size += info.file_size
        if total_size > limits.max_uncompressed_bytes:
            raise WorkbookSecurityError("archive total size limit exceeded")

        if info.file_size:
            if info.compress_size == 0:
                raise WorkbookSecurityError("archive compression ratio exceeded")
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise WorkbookSecurityError("archive compression ratio exceeded")


def _contains_dtd_or_entity(xml_bytes: bytes) -> bool:
    # Removing NULs also catches the common UTF-16 encodings without decoding
    # attacker-controlled declarations first.
    declaration_scan = xml_bytes.replace(b"\x00", b"").upper()
    return b"<!DOCTYPE" in declaration_scan or b"<!ENTITY" in declaration_scan


def _validate_xml(xml_bytes: bytes, *, relationship_part: bool) -> None:
    if _contains_dtd_or_entity(xml_bytes):
        raise WorkbookSecurityError("DTD or entity declaration is not permitted")
    try:
        root = ElementTree.fromstring(xml_bytes)
    except (ElementTree.ParseError, LookupError, ValueError) as exc:
        raise WorkbookSecurityError("malformed workbook XML") from exc

    if not relationship_part:
        return
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name != _RELATIONSHIP_TAG:
            continue
        attributes = {
            key.rsplit("}", 1)[-1].casefold(): value
            for key, value in element.attrib.items()
        }
        target_mode = (attributes.get("targetmode") or "").strip().casefold()
        if target_mode == "external":
            # Upload parsers never need remote, file, UNC, or other package-external
            # targets. Rejecting them avoids ambiguous downstream consumers.
            raise WorkbookSecurityError("external workbook relationship is not permitted")


def _read_and_validate_members(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    *,
    limits: WorkbookSecurityLimits,
) -> None:
    actual_total = 0
    for info in infos:
        if info.is_dir():
            continue

        is_xml = info.filename.casefold().endswith((".xml", ".rels"))
        xml_chunks: list[bytes] | None = [] if is_xml else None
        member_size = 0
        try:
            with archive.open(info, mode="r") as member:
                while True:
                    chunk = member.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    member_size += len(chunk)
                    actual_total += len(chunk)
                    if (
                        member_size > limits.max_entry_bytes
                        or actual_total > limits.max_uncompressed_bytes
                    ):
                        raise WorkbookSecurityError("archive expansion limit exceeded")
                    if xml_chunks is not None:
                        xml_chunks.append(chunk)
        except WorkbookSecurityError:
            raise
        except Exception as exc:
            raise WorkbookSecurityError("malformed workbook archive") from exc

        if member_size != info.file_size:
            raise WorkbookSecurityError("archive member size mismatch")
        if xml_chunks is not None:
            _validate_xml(
                b"".join(xml_chunks),
                relationship_part=info.filename.casefold().endswith(".rels"),
            )


def preflight_xlsx_archive(
    file_bytes: bytes,
    *,
    limits: WorkbookSecurityLimits,
) -> None:
    """Bound and validate an OOXML ZIP before any openpyxl parsing occurs."""

    limits.validate()
    if len(file_bytes) > limits.max_compressed_bytes:
        raise WorkbookSecurityError("compressed workbook size limit exceeded")
    directory = _read_central_directory(file_bytes, limits=limits)
    _validate_raw_central_directory_names(
        file_bytes,
        directory=directory,
    )
    try:
        with zipfile.ZipFile(BytesIO(file_bytes), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != directory.entry_count or archive.start_dir != directory.start:
                raise WorkbookSecurityError("archive entry count mismatch")
            _validate_member_metadata(infos, limits=limits)
            _read_and_validate_members(archive, infos, limits=limits)
    except WorkbookSecurityError:
        raise
    except Exception as exc:
        raise WorkbookSecurityError("malformed workbook archive") from exc
