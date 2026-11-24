"""S3Storage (production: Backblaze B2 or Cloudflare R2) against moto's S3 emulator over real HTTP.

This is the only code path between the app and the production bucket, so it gets a real
round-trip test: upload, download, presigned URL, and prefix deletion.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from moto.server import ThreadedMotoServer
from pydantic import SecretStr

from app.core.config import get_settings
from app.integrations.storage import S3Storage, StorageError, document_key, s3_region_for


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Storage]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    s = get_settings()
    for name, value in {
        "s3_endpoint_url": f"http://{host}:{port}",
        "s3_bucket": "documind-test",
        "s3_access_key_id": SecretStr("test-key"),
        "s3_secret_access_key": SecretStr("test-secret"),
        "s3_region": "us-east-1",
    }.items():
        monkeypatch.setattr(s, name, value)
    storage = S3Storage()
    storage.client.create_bucket(Bucket="documind-test")
    yield storage
    server.stop()


async def test_round_trip_presign_and_prefix_delete(s3: S3Storage, tmp_path: Path) -> None:
    ws = uuid.uuid4()
    keys = [document_key(ws, uuid.uuid4()) for _ in range(3)]
    other = document_key(uuid.uuid4(), uuid.uuid4())  # another workspace's file
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.7 hello r2")
    for key in [*keys, other]:
        await s3.put_file(key, src, "application/pdf")

    out = tmp_path / "out.pdf"
    await s3.download_to(keys[0], out)
    assert out.read_bytes() == b"%PDF-1.7 hello r2"

    url = await s3.presigned_download_url(keys[0], "Résumé 2026.pdf", "application/pdf")
    assert url is not None and "X-Amz-Expires=60" in url
    async with httpx.AsyncClient() as http:
        resp = await http.get(url)
    assert resp.content == b"%PDF-1.7 hello r2"
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%202026.pdf" in disposition

    await s3.delete_prefix(f"ws/{ws}/")
    remaining = [
        o["Key"] for o in s3.client.list_objects_v2(Bucket="documind-test").get("Contents", [])
    ]
    assert remaining == [other]  # only this workspace's files were removed


async def test_missing_object_raises_storage_error(s3: S3Storage, tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        await s3.download_to("ws/nope/docs/nope/x", tmp_path / "x")


def test_backblaze_region_is_read_from_the_endpoint() -> None:
    assert s3_region_for("https://s3.us-west-004.backblazeb2.com", "auto") == "us-west-004"
    assert (
        s3_region_for("https://acct.r2.cloudflarestorage.com", "auto") == "auto"
    )  # R2 wants "auto"
    assert (
        s3_region_for("https://s3.us-west-004.backblazeb2.com", "eu-x") == "eu-x"
    )  # explicit wins
