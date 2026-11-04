"""Mirror source files to Cloudflare R2 and add "Mirror" sources to entries."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlsplit

import requests

from catalog import config
from catalog.entries import ROOT, load_entries, write_entry
from catalog.files import read_head, reject_html, response_filename
from catalog.http import make_session

R2_ENV_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _clean(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    return re.sub(r"_+", "_", text)


def safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", unquote(name))
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = _clean(stem).strip("_.")
    ext = _clean(ext).replace(".", "_").strip("_")
    stem = stem or "file"
    return f"{stem}.{ext}" if ext else stem


def mirror_key(sha256: str, filename: str) -> str:
    return f"files/{sha256}/{safe_filename(filename)}"


def mirror_url(key: str) -> str:
    return config.MIRROR_BASE + key


def is_mirror_url(url: str) -> bool:
    """True if url is on MIRROR_BASE (scheme and host compared case-insensitively)."""
    base = urlsplit(config.MIRROR_BASE)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".")
    except ValueError:
        return False
    return (parts.scheme.lower() == base.scheme and host == base.hostname and parts.port is None
            and parts.path.startswith(base.path))


class Uploader(Protocol):
    def exists(self, key: str) -> bool: ...

    def find(self, sha256: str) -> str | None:
        """Key of an object already stored under files/<sha256>/, or None."""
        ...

    def upload(self, path: Path, key: str) -> None: ...


class MemoryUploader:
    """In-memory uploader for tests and dry runs."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.objects

    def find(self, sha256: str) -> str | None:
        prefix = f"files/{sha256}/"
        return next((k for k in self.objects if k.startswith(prefix)), None)

    def upload(self, path: Path, key: str) -> None:
        self.objects[key] = Path(path).read_bytes()


class R2Uploader:
    def __init__(self, client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls) -> R2Uploader:
        missing = [v for v in R2_ENV_VARS if not os.environ.get(v)]
        if missing:
            raise RuntimeError("missing R2 environment variables: " + ", ".join(missing))
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        return cls(client, os.environ["R2_BUCKET"])

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def find(self, sha256: str) -> str | None:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=f"files/{sha256}/", MaxKeys=1)
        contents = resp.get("Contents") or []
        return contents[0]["Key"] if contents else None

    def upload(self, path: Path, key: str) -> None:
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.client.upload_file(
            str(path), self.bucket, key, ExtraArgs={"ContentType": content_type}
        )


@dataclass(frozen=True)
class Mirrored:
    url: str
    sha256: str
    size: int


def mirror_file(path: Path, filename: str, uploader: Uploader) -> Mirrored:
    sha256, size = hash_file(path)
    return _mirror_hashed(path, filename, sha256, size, uploader)


def _mirror_hashed(path: Path, filename: str, sha256: str, size: int, uploader: Uploader) -> Mirrored:
    """Store the file once per sha256: reuse any key already under files/<sha256>/."""
    key = uploader.find(sha256)
    if key is None:
        key = mirror_key(sha256, filename)
        uploader.upload(path, key)
    return Mirrored(url=mirror_url(key), sha256=sha256, size=size)


def make_mirror_source(original: dict, m: Mirrored) -> dict:
    source = {k: original[k] for k in ("platform", "install", "steps") if k in original}
    source.update(label="Mirror", url=m.url, sha256=m.sha256, size=m.size)
    return source


def unmirrored_source_indexes(entry: dict) -> list[int]:
    sources = [s for s in entry.get("sources") or [] if isinstance(s, dict)]
    mirrored = {s.get("sha256") for s in sources if is_mirror_url(str(s.get("url", "")))}
    return [
        i
        for i, s in enumerate(entry.get("sources") or [])
        if isinstance(s, dict)
        and not is_mirror_url(str(s.get("url", "")))
        and not config.is_forbidden_url(str(s.get("url", "")))
        and s.get("platform") != "web"
        and (s.get("install") or {}).get("method") != "url"
        and (s.get("sha256") is None or s["sha256"] not in mirrored)
    ]


def _download(session: requests.Session, url: str, download_dir: Path) -> tuple[Path, str]:
    """Download url into download_dir; reject web pages; name it from the response (see catalog.files)."""
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=download_dir, suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with session.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            head = read_head(tmp)
            reject_html(resp.headers.get("Content-Type"), head, url)
            filename = response_filename(resp, head)
        dest = download_dir / safe_filename(filename)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest, filename


def mirror_entries(
    entries_dir: Path,
    *,
    uploader: Uploader,
    session: requests.Session,
    download_dir: Path,
    only: Iterable[str] | None = None,
    write: bool = True,
) -> list[str]:
    wanted = set(only) if only is not None else None
    changed: list[str] = []
    for entry_id, entry in load_entries(entries_dir).items():
        if wanted is not None and entry_id not in wanted:
            continue
        dirty = False
        # Walk indexes high to low so insertions don't shift pending ones.
        for i in reversed(unmirrored_source_indexes(entry)):
            source = entry["sources"][i]
            try:
                path, filename = _download(session, source["url"], download_dir)
                sha256, size = hash_file(path)
                recorded = source.get("sha256")
                if recorded is not None and recorded != sha256:
                    print(f"{entry_id}: warning: {source['url']} has sha256 {sha256}, but the entry "
                          f"records {recorded}; not mirrored", file=sys.stderr)
                    continue
                m = _mirror_hashed(path, filename, sha256, size, uploader)
            except Exception as exc:
                print(f"{entry_id}: {exc}")
                continue
            source.setdefault("sha256", m.sha256)
            source.setdefault("size", m.size)
            have = {s.get("sha256") for s in entry["sources"] if is_mirror_url(str(s.get("url", "")))}
            if m.sha256 not in have:
                entry["sources"].insert(i + 1, make_mirror_source(source, m))
            dirty = True
        if dirty:
            if write:
                write_entry(entries_dir, entry, overwrite=True)
            changed.append(entry_id)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-mirror", description="Mirror entry sources to R2.")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="use an in-memory uploader and write no files")
    args = parser.parse_args(argv)

    uploader: Uploader = MemoryUploader() if args.dry_run else R2Uploader.from_env()
    with tempfile.TemporaryDirectory() as tmp:
        changed = mirror_entries(
            args.entries,
            uploader=uploader,
            session=make_session(),
            download_dir=args.download_dir or Path(tmp),
            only=args.only,
            write=not args.dry_run,
        )
    for entry_id in changed:
        print(entry_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
