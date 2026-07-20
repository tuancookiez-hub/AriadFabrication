"""Canonicalize volatile exporter metadata for reproducible artifact hashes."""

from __future__ import annotations

from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


_STEP_TIMESTAMP = re.compile(
    r"(FILE_NAME\('Open CASCADE Shape Model',)'[^']*'",
    re.MULTILINE,
)
_STEP_PRODUCT = re.compile(r"'Open CASCADE STEP translator [^']*'")
_THREEMF_CREATION_DATE = re.compile(
    rb'(<metadata name="CreationDate">)[^<]*(</metadata>)'
)


def canonicalize_step(path: Path) -> None:
    """Remove timestamp and per-process counters from an OCCT STEP header."""

    content = path.read_text(encoding="utf-8")
    content, timestamp_count = _STEP_TIMESTAMP.subn(
        r"\1'1970-01-01T00:00:00'",
        content,
        count=1,
    )
    content, product_count = _STEP_PRODUCT.subn("'Ariad deterministic STEP export'", content)
    if timestamp_count != 1 or product_count < 1:
        raise ValueError("unexpected OCCT STEP header; deterministic canonicalization aborted")
    path.write_text(content, encoding="utf-8", newline="\n")


def canonicalize_3mf(path: Path) -> None:
    """Fix 3MF creation metadata, member order, and ZIP timestamps."""

    with ZipFile(path) as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    model_name = next((name for name in members if name.lower().endswith(".model")), None)
    if model_name is None:
        raise ValueError("3MF package does not contain a model document")
    model, count = _THREEMF_CREATION_DATE.subn(
        rb"\g<1>1970-01-01T00:00:00\g<2>",
        members[model_name],
        count=1,
    )
    if count != 1:
        raise ValueError("3MF model does not contain the expected CreationDate metadata")
    members[model_name] = model

    temporary = path.with_suffix(path.suffix + ".canonical")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, members[name], compress_type=ZIP_DEFLATED, compresslevel=9)
    temporary.replace(path)
