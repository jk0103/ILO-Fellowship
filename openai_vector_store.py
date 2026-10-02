"""Put a chapter file into an OpenAI vector store, so the generators can cite it.

The chapter is uploaded once, attached to a vector store, and then indexed by
OpenAI; the vector store id it prints is what the generators pass to
file_search.

CLI:
    export OPENAI_API_KEY=...
    python openai_vector_store.py "Introduction to Logic - Chapter 10.html"
    python openai_vector_store.py chapter.html --store vs_existing  # add to one
"""

import argparse
import os
import sys
import time

import requests

import load_env

load_env.load()

BASE = "https://api.openai.com/v1"
HEADERS_EXTRA = {"OpenAI-Beta": "assistants=v2"}


class VectorStoreError(RuntimeError):
    """The upload, the store, or the indexing did not work out."""


def _auth(api_key):
    return {"Authorization": f"Bearer {api_key}", **HEADERS_EXTRA}


def _post(api_key, path, **kwargs):
    try:
        r = requests.post(f"{BASE}{path}", headers=_auth(api_key), timeout=180,
                          **kwargs)
    except requests.RequestException as exc:
        raise VectorStoreError(f"Could not reach the OpenAI API: {exc}") from exc
    if r.status_code >= 400:
        raise VectorStoreError(f"POST {path} returned {r.status_code}: "
                               f"{r.text[:500]}")
    return r.json()


def _get(api_key, path):
    try:
        r = requests.get(f"{BASE}{path}", headers=_auth(api_key), timeout=60)
    except requests.RequestException as exc:
        raise VectorStoreError(f"Could not reach the OpenAI API: {exc}") from exc
    if r.status_code >= 400:
        raise VectorStoreError(f"GET {path} returned {r.status_code}: "
                               f"{r.text[:500]}")
    return r.json()


def as_utf8(raw):
    """The file's bytes as UTF-8.

    Some chapters are saved as Windows-1252, where ¬ is the single byte 0xAC.
    Sent as-is, the indexer reads them as UTF-8 and every negation turns into a
    replacement character — in a logic text, that loses the meaning."""
    try:
        raw.decode("utf-8")
        return raw
    except UnicodeDecodeError:
        return raw.decode("cp1252").encode("utf-8")


def upload_file(path, api_key):
    """Upload one local file and return its file id."""
    with open(path, "rb") as fh:
        body = as_utf8(fh.read())
    data = _post(api_key, "/files",
                 files={"file": (os.path.basename(path), body, "text/html")},
                 data={"purpose": "assistants"})
    return data["id"]


def create_store(name, api_key):
    return _post(api_key, "/vector_stores", json={"name": name})["id"]


def attach(store_id, file_id, api_key):
    return _post(api_key, f"/vector_stores/{store_id}/files",
                 json={"file_id": file_id})


def wait_indexed(store_id, file_id, api_key, timeout=300, interval=3):
    """Block until OpenAI has chunked and embedded the file."""
    deadline = time.time() + timeout
    while True:
        entry = _get(api_key, f"/vector_stores/{store_id}/files/{file_id}")
        status = entry.get("status")
        if status == "completed":
            return entry
        if status == "failed":
            raise VectorStoreError(
                f"Indexing failed: {entry.get('last_error')}")
        if time.time() > deadline:
            raise VectorStoreError(
                f"File is still {status!r} after {timeout}s.")
        time.sleep(interval)


def ingest(path, api_key=None, store_id=None, store_name=None):
    """Upload path, attach it to a store, wait for indexing, return the ids."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise VectorStoreError("OPENAI_API_KEY is not set.")
    if not os.path.exists(path):
        raise VectorStoreError(f"No such file: {path}")

    file_id = upload_file(path, api_key)
    if not store_id:
        store_id = create_store(
            store_name or os.path.splitext(os.path.basename(path))[0], api_key)
    attach(store_id, file_id, api_key)
    wait_indexed(store_id, file_id, api_key)
    return {"file_id": file_id, "vector_store_id": store_id}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="local file to upload")
    ap.add_argument("--store", help="attach to this existing vector store id")
    ap.add_argument("--name", help="name for a newly created vector store")
    args = ap.parse_args(argv)
    try:
        ids = ingest(args.path, store_id=args.store, store_name=args.name)
    except VectorStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"file_id:         {ids['file_id']}")
    print(f"vector_store_id: {ids['vector_store_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
