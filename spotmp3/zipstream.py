import unicodedata
import zipfile
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import quote

READ_BLOCK_BYTES = 1024 * 1024
STORE_WITHOUT_COMPRESSING = 0
RFC5987_SAFE_CHARACTERS = "!#$&+-.^_`|~"


class _PendingBytes:
    def __init__(self):
        self._parts: list[bytes] = []

    def write(self, data) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


def stream_zip(entries: Iterable[tuple[Path, str]]) -> Iterator[bytes]:
    pending = _PendingBytes()
    with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, compresslevel=STORE_WITHOUT_COMPRESSING) as bundle:
        for path, name in entries:
            try:
                source = path.open("rb")
            except FileNotFoundError:
                continue
            with source, bundle.open(name, "w") as entry:
                while block := source.read(READ_BLOCK_BYTES):
                    entry.write(block)
                    if chunk := pending.take():
                        yield chunk
    if chunk := pending.take():
        yield chunk


def attachment_names(download_name: str) -> dict[str, str]:
    try:
        download_name.encode("ascii")
    except UnicodeEncodeError:
        simple = unicodedata.normalize("NFKD", download_name).encode("ascii", "ignore").decode("ascii")
        return {"filename": simple, "filename*": f"UTF-8''{quote(download_name, safe=RFC5987_SAFE_CHARACTERS)}"}
    return {"filename": download_name}
