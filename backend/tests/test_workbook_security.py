from __future__ import annotations

import stat
import struct
import warnings
import zipfile
from io import BytesIO

import pytest

from app.services.parser_common import (
    UploadSizeLimitError,
    UploadValidationError,
    default_workbook_readability_hook,
    read_upload_bytes_limited,
    validate_upload_payload,
)
from app.services.workbook_security import (
    WORKBOOK_READ_ERROR,
    WorkbookSecurityError,
    WorkbookSecurityLimits,
    preflight_xlsx_archive,
)


def _limits(**overrides: int | float) -> WorkbookSecurityLimits:
    values: dict[str, int | float] = {
        "max_compressed_bytes": 1024 * 1024,
        "max_uncompressed_bytes": 2 * 1024 * 1024,
        "max_entries": 100,
        "max_entry_bytes": 1024 * 1024,
        "max_compression_ratio": 100.0,
    }
    values.update(overrides)
    return WorkbookSecurityLimits(**values)  # type: ignore[arg-type]


def _zip_bytes(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


def _set_encrypted_flags(payload: bytes) -> bytes:
    mutated = bytearray(payload)
    offset = 0
    while True:
        offset = mutated.find(b"PK\x03\x04", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", mutated, offset + 6)[0]
        struct.pack_into("<H", mutated, offset + 6, flags | 0x1)
        offset += 4
    offset = 0
    while True:
        offset = mutated.find(b"PK\x01\x02", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", mutated, offset + 8)[0]
        struct.pack_into("<H", mutated, offset + 8, flags | 0x1)
        offset += 4
    return bytes(mutated)


class _ChunkedUpload:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0
        self.requested_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        if self.offset >= len(self.payload):
            return b""
        end = len(self.payload) if size < 0 else self.offset + size
        chunk = self.payload[self.offset : end]
        self.offset += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_upload_reader_enforces_size_while_streaming() -> None:
    accepted = _ChunkedUpload(b"a" * 10)
    assert await read_upload_bytes_limited(
        accepted,
        max_size_bytes=10,
        chunk_size=4,
    ) == b"a" * 10
    assert all(size <= 4 for size in accepted.requested_sizes)

    rejected = _ChunkedUpload(b"b" * 11)
    with pytest.raises(UploadSizeLimitError, match="exceeds"):
        await read_upload_bytes_limited(
            rejected,
            max_size_bytes=10,
            chunk_size=4,
        )
    assert rejected.offset == 11


def test_valid_bounded_archive_passes() -> None:
    payload = _zip_bytes(
        [
            ("[Content_Types].xml", b"<Types/>"),
            ("xl/workbook.xml", b"<workbook/>"),
            ("xl/_rels/workbook.xml.rels", b"<Relationships/>"),
        ]
    )

    preflight_xlsx_archive(payload, limits=_limits())


@pytest.mark.parametrize(
    ("payload", "limits"),
    [
        (_zip_bytes([("one.xml", b"<x/>")]), _limits(max_compressed_bytes=10)),
        (
            _zip_bytes([("one.xml", b"<x>12345</x>")]),
            _limits(max_entry_bytes=5),
        ),
        (
            _zip_bytes([("one.bin", b"12345"), ("two.bin", b"67890")]),
            _limits(max_uncompressed_bytes=9),
        ),
        (
            _zip_bytes([("one.xml", b"<x/>"), ("two.xml", b"<x/>")]),
            _limits(max_entries=1),
        ),
        (
            _zip_bytes(
                [("high-ratio.bin", b"A" * 10_000)],
                compression=zipfile.ZIP_DEFLATED,
            ),
            _limits(max_compression_ratio=2.0),
        ),
    ],
)
def test_archive_resource_limits_are_enforced(
    payload: bytes,
    limits: WorkbookSecurityLimits,
) -> None:
    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=limits)


@pytest.mark.parametrize(
    "member_name",
    [
        "../evil.xml",
        "/absolute.xml",
        "C:/evil.xml",
        "a\\b.xml",
        "xl/./evil.xml",
        "xl//evil.xml",
    ],
)
def test_archive_traversal_and_ambiguous_names_are_rejected(member_name: str) -> None:
    archive_name = member_name.replace("\\", "/")
    payload = _zip_bytes([(archive_name, b"<x/>")])
    if "\\" in member_name:
        # zipfile rewrites backslashes while creating archives on Windows.
        # Patch both equal-length raw directory names to preserve the attack.
        payload = payload.replace(archive_name.encode(), member_name.encode())

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_duplicate_members_are_rejected() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        payload = _zip_bytes(
            [("xl/workbook.xml", b"<a/>"), ("XL/WORKBOOK.XML", b"<b/>")]
        )

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_forged_central_directory_entry_count_is_rejected() -> None:
    payload = bytearray(
        _zip_bytes([("one.xml", b"<one/>"), ("two.xml", b"<two/>")])
    )
    end_record = payload.rfind(b"PK\x05\x06")
    assert end_record >= 0
    struct.pack_into("<H", payload, end_record + 8, 1)
    struct.pack_into("<H", payload, end_record + 10, 1)

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(bytes(payload), limits=_limits())


def test_symlink_member_is_rejected() -> None:
    info = zipfile.ZipInfo("xl/workbook.xml")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    payload = _zip_bytes([(info, b"target.xml")])

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_encrypted_member_is_rejected() -> None:
    payload = _set_encrypted_flags(_zip_bytes([("xl/workbook.xml", b"<workbook/>")]))

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_bad_crc_and_malformed_zip_are_rejected() -> None:
    crc_payload = _zip_bytes([("payload.bin", b"crc-payload")])
    corrupted = crc_payload.replace(b"crc-payload", b"bad-payload", 1)

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(corrupted, limits=_limits())
    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(b"not-a-zip", limits=_limits())


@pytest.mark.parametrize(
    "xml_payload",
    [
        b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>',
        b"<broken>",
    ],
)
def test_unsafe_or_malformed_xml_is_rejected(xml_payload: bytes) -> None:
    payload = _zip_bytes([("xl/workbook.xml", xml_payload)])

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


@pytest.mark.parametrize(
    ("codec", "declared_encoding"),
    [
        ("utf-16", "UTF-16"),
        ("utf-16-be", "UTF-16BE"),
        ("utf-32", "UTF-32"),
    ],
)
def test_encoded_entity_declarations_are_rejected(
    codec: str,
    declared_encoding: str,
) -> None:
    xml_payload = (
        f'<?xml version="1.0" encoding="{declared_encoding}"?>'
        '<!DOCTYPE workbook [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        "<workbook>&secret;</workbook>"
    ).encode(codec)
    payload = _zip_bytes([("xl/workbook.xml", xml_payload)])

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


@pytest.mark.parametrize(
    "xml_payload",
    [
        b"<!DOCTYPE workbook><workbook/>",
        (
            b"<!DOCTYPE workbook ["
            b'<!ENTITY a "1234567890">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
            b"]><workbook>&c;</workbook>"
        ),
    ],
)
def test_hardened_parser_rejects_declarations_if_fast_scan_misses(
    monkeypatch: pytest.MonkeyPatch,
    xml_payload: bytes,
) -> None:
    monkeypatch.setattr(
        "app.services.workbook_security._contains_dtd_or_entity",
        lambda _xml_bytes: False,
    )
    payload = _zip_bytes([("xl/workbook.xml", xml_payload)])

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_external_relationship_is_rejected() -> None:
    relationships = b"""
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="example" Target="file:///private/data" TargetMode="External"/>
    </Relationships>
    """
    payload = _zip_bytes([("xl/_rels/workbook.xml.rels", relationships)])

    with pytest.raises(WorkbookSecurityError):
        preflight_xlsx_archive(payload, limits=_limits())


def test_deeply_nested_external_relationship_is_rejected() -> None:
    depth = 1_500
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + ("<wrapper>" * depth)
        + '<Relationship Id="rId1" Type="example" '
        'Target="file:///private/data" TargetMode="External"/>'
        + ("</wrapper>" * depth)
        + "</Relationships>"
    ).encode()
    payload = _zip_bytes([("xl/_rels/workbook.xml.rels", relationships)])

    with pytest.raises(
        WorkbookSecurityError,
        match="external workbook relationship",
    ):
        preflight_xlsx_archive(payload, limits=_limits())


def test_preflight_failure_is_generic_and_occurs_before_openpyxl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openpyxl_called = False

    def _unexpected_openpyxl_call(*args, **kwargs):
        nonlocal openpyxl_called
        openpyxl_called = True
        raise AssertionError("openpyxl must not receive an unsafe archive")

    monkeypatch.setattr("openpyxl.load_workbook", _unexpected_openpyxl_call)
    payload = _zip_bytes(
        [("xl/workbook.xml", b"<!DOCTYPE x><workbook/>")],
    )

    with pytest.raises(UploadValidationError) as exc_info:
        default_workbook_readability_hook(payload)

    assert str(exc_info.value) == WORKBOOK_READ_ERROR
    assert openpyxl_called is False


def test_custom_readability_hook_cannot_bypass_archive_preflight() -> None:
    custom_hook_called = False

    def _custom_hook(file_bytes: bytes) -> None:
        nonlocal custom_hook_called
        custom_hook_called = True

    payload = _zip_bytes(
        [("xl/workbook.xml", b"<!DOCTYPE x><workbook/>")],
    )

    with pytest.raises(UploadValidationError) as exc_info:
        validate_upload_payload(
            upload_type="ttf",
            filename="ttf.xlsx",
            file_bytes=payload,
            workbook_hook=_custom_hook,
        )

    assert str(exc_info.value) == WORKBOOK_READ_ERROR
    assert custom_hook_called is False


def test_csv_upload_path_is_unchanged() -> None:
    payload = b"Date,Holiday\n2026-01-01,New Year"

    validated = validate_upload_payload(
        upload_type="public_holidays",
        filename="holidays.csv",
        file_bytes=payload,
        max_size_bytes=1024,
    )

    assert validated.extension == ".csv"
    assert validated.file_bytes == payload
