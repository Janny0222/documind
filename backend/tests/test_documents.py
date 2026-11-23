"""Documents & collections through the API, with real files and the real job queue."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text, update

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations.storage import get_storage
from app.models import DocumentChunk, DocumentPage, ProcessingJob
from app.workers import handlers
from app.workers.runner import drain
from tests.conftest import ApiClient, UserFactory, personal_workspace_id
from tests.files import LOREM, make_docx, make_pdf

PDF_MIME = "application/pdf"


async def upload(client: ApiClient, ws: str, *files: tuple[str, bytes, str]) -> list[dict]:  # type: ignore[type-arg]
    r = await client.post(f"/api/v1/workspaces/{ws}/documents", files=[("files", f) for f in files])
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def get_doc(client: ApiClient, ws: str, doc_id: str) -> dict:  # type: ignore[type-arg]
    r = await client.get(f"/api/v1/workspaces/{ws}/documents/{doc_id}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def count(model: type, **where: object) -> int:
    async with get_sessionmaker()() as db:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return (await db.execute(stmt)).scalar_one()


# ------------------------------------------------------------------ happy path


async def test_upload_index_preview_download(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    pdf = make_pdf(
        [LOREM * 3, "Second page: the cancellation policy allows refunds within 14 days."]
    )

    [result] = await upload(alice, ws, ("Employee Handbook.pdf", pdf, PDF_MIME))
    assert result["outcome"] == "created"
    doc = result["document"]
    assert doc["status"] == "queued"
    assert doc["file_type"] == "pdf"
    assert doc["title"] == "Employee Handbook"

    assert await drain() == 1
    doc = await get_doc(alice, ws, doc["id"])
    assert doc["status"] == "ready"
    assert doc["page_count"] == 2 and doc["page_unit"] == "page"
    assert doc["chunk_count"] >= 2

    page = (await alice.get(f"/api/v1/workspaces/{ws}/documents/{doc['id']}/pages/2")).json()
    assert "cancellation policy" in page["text"]
    assert page["page_count"] == 2

    link = (await alice.get(f"/api/v1/workspaces/{ws}/documents/{doc['id']}/download")).json()
    file = await alice.get(link["url"])
    assert file.status_code == 200
    assert file.content == pdf
    assert file.headers["content-disposition"].startswith("attachment;")


async def test_docx_uses_sections_not_invented_pages(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    data = make_docx([("h1", "Benefits"), ("p", LOREM * 2)])
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    [result] = await upload(alice, ws, ("policy.docx", data, mime))
    await drain()
    doc = await get_doc(alice, ws, result["document"]["id"])
    assert doc["status"] == "ready"
    assert doc["page_unit"] == "section"


async def test_list_search_filter_sort_and_counts(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    await upload(
        alice,
        ws,
        ("Zeta report.pdf", make_pdf(["zeta " + LOREM]), PDF_MIME),
        ("alpha notes.txt", b"alpha " + LOREM.encode(), "text/plain"),
        ("100% match_test.txt", b"percent " + LOREM.encode(), "text/plain"),
    )
    base = f"/api/v1/workspaces/{ws}/documents"
    listing = (await alice.get(base, params={"sort": "name"})).json()
    assert [d["title"] for d in listing["items"]] == [
        "100% match_test",
        "alpha notes",
        "Zeta report",
    ]
    assert listing["counts"] == {"all": 3, "pdf": 1, "docx": 0, "txt": 2}

    only_txt = (await alice.get(base, params={"type": "txt"})).json()
    assert only_txt["total"] == 2
    assert only_txt["counts"]["all"] == 3  # pill counts ignore the type filter

    # LIKE wildcards are matched literally: "%" must not match everything.
    assert (await alice.get(base, params={"q": "100%"})).json()["total"] == 1
    assert (await alice.get(base, params={"q": "zet_"})).json()[
        "total"
    ] == 0  # "_" is not a wildcard
    assert (await alice.get(base, params={"q": "h_t"})).json()[
        "total"
    ] == 1  # ...but matches a real "_"
    assert (await alice.get(base, params={"q": "ZETA"})).json()["total"] == 1


# ------------------------------------------------------------------ rejection & limits


async def test_bad_files_are_rejected_per_file(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    results = await upload(
        alice,
        ws,
        ("ok.txt", LOREM.encode(), "text/plain"),
        ("fake.pdf", b"not really a pdf", PDF_MIME),
        ("virus.exe", b"MZ", "application/octet-stream"),
        ("../../etc/passwd.txt", b"root:x:0:0 " + LOREM.encode(), "text/plain"),
    )
    outcomes = [(r["filename"], r["outcome"], r.get("code")) for r in results]
    assert outcomes == [
        ("ok.txt", "created", None),
        ("fake.pdf", "rejected", "content_mismatch"),
        ("virus.exe", "rejected", "unsupported_type"),
        ("passwd.txt", "created", None),  # path components stripped from the display name
    ]
    # The storage key is server-generated and never derived from the filename.
    async with get_sessionmaker()() as db:
        keys = (await db.execute(text("select storage_key from documents"))).scalars().all()
    assert all(k.startswith(f"ws/{ws}/docs/") and "passwd" not in k for k in keys)


async def test_file_size_limit(make_user: UserFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("big.txt", b"a " * (600 * 1024), "text/plain"))
    assert (r["outcome"], r["code"]) == ("rejected", "file_too_large")


async def test_duplicate_upload_reuses_existing(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    data = make_pdf([LOREM])
    [first] = await upload(alice, ws, ("a.pdf", data, PDF_MIME))
    [second] = await upload(alice, ws, ("copy.pdf", data, PDF_MIME))
    assert second["outcome"] == "duplicate"
    assert second["document"]["id"] == first["document"]["id"]


async def test_document_limit(make_user: UserFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_documents_per_workspace", 1)
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    results = await upload(
        alice,
        ws,
        ("1.txt", b"one " + LOREM.encode(), "text/plain"),
        ("2.txt", b"two " + LOREM.encode(), "text/plain"),
    )
    assert [r["outcome"] for r in results] == ["created", "rejected"]
    assert results[1]["code"] == "document_limit"


async def test_scanned_and_encrypted_pdfs_fail_with_a_clear_reason(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    results = await upload(
        alice,
        ws,
        ("scan.pdf", make_pdf(["", ""]), PDF_MIME),
        ("locked.pdf", make_pdf(["x"], password="pw"), PDF_MIME),
    )
    await drain()
    scan = await get_doc(alice, ws, results[0]["document"]["id"])
    locked = await get_doc(alice, ws, results[1]["document"]["id"])
    assert (scan["status"], scan["error_code"]) == ("failed", "no_text")
    assert "OCR" in scan["error_message"]
    assert (locked["status"], locked["error_code"]) == ("failed", "encrypted_pdf")
    # Permanent failures are not retried.
    async with get_sessionmaker()() as db:
        statuses = (await db.execute(select(ProcessingJob.status))).scalars().all()
    assert statuses == ["failed", "failed"]


# ------------------------------------------------------------------ jobs: retries, idempotency, leases


async def test_transient_errors_retry_then_succeed(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("a.pdf", make_pdf([LOREM]), PDF_MIME))

    real = handlers._download_and_parse
    calls = {"n": 0}

    async def flaky(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("storage hiccup")
        return await real(*args, **kwargs)

    monkeypatch.setattr(handlers, "_download_and_parse", flaky)
    await drain()
    async with get_sessionmaker()() as db:
        job = (await db.execute(select(ProcessingJob))).scalar_one()
        assert (job.status, job.attempts) == ("retry", 1)
        # Skip the backoff wait.
        await db.execute(update(ProcessingJob).values(run_after=func.now()))
        await db.commit()
    await drain()
    assert (await get_doc(alice, ws, r["document"]["id"]))["status"] == "ready"


async def test_gives_up_after_max_attempts(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("a.pdf", make_pdf([LOREM]), PDF_MIME))

    async def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ConnectionError("storage down")

    monkeypatch.setattr(handlers, "_download_and_parse", broken)
    for _ in range(get_settings().job_max_attempts):
        await drain()
        async with get_sessionmaker()() as db:
            await db.execute(update(ProcessingJob).values(run_after=func.now()))
            await db.commit()
    doc = await get_doc(alice, ws, r["document"]["id"])
    assert (doc["status"], doc["error_code"]) == ("failed", "processing_error")

    # The user can retry once the problem is fixed.
    monkeypatch.undo()
    reprocess = await alice.post(f"/api/v1/workspaces/{ws}/documents/{doc['id']}/reprocess")
    assert reprocess.json()["status"] == "queued"
    await drain()
    assert (await get_doc(alice, ws, doc["id"]))["status"] == "ready"


async def test_reindexing_is_idempotent(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("a.pdf", make_pdf([LOREM * 10, LOREM * 10]), PDF_MIME))
    await drain()
    doc_id = uuid.UUID(r["document"]["id"])
    chunks_before = await count(DocumentChunk, document_id=doc_id)

    # Simulate a duplicate delivery of the same job.
    async with get_sessionmaker()() as db:
        db.add(ProcessingJob(kind="index_document", workspace_id=uuid.UUID(ws), document_id=doc_id))
        await db.commit()
    await drain()
    assert await count(DocumentChunk, document_id=doc_id) == chunks_before
    assert await count(DocumentPage, document_id=doc_id) == 2


async def test_expired_lease_is_reclaimed(make_user: UserFactory) -> None:
    """If the host sleeps or crashes mid-job, the job runs again once its lease expires."""
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("a.pdf", make_pdf([LOREM]), PDF_MIME))
    async with get_sessionmaker()() as db:
        await db.execute(
            update(ProcessingJob).values(
                status="running", attempts=1, locked_until=func.now() - text("interval '1 minute'")
            )
        )
        await db.commit()
    assert await drain() == 1
    assert (await get_doc(alice, ws, r["document"]["id"]))["status"] == "ready"


async def test_internal_drain_endpoint_requires_secret(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await make_user()
    assert (
        await alice.post("/api/v1/internal/jobs/drain")
    ).status_code == 404  # disabled by default
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "internal_api_secret", SecretStr("s3cret-value"))
    assert (
        await alice.post("/api/v1/internal/jobs/drain", headers={"X-Internal-Secret": "nope"})
    ).status_code == 401
    ok = await alice.post(
        "/api/v1/internal/jobs/drain", headers={"X-Internal-Secret": "s3cret-value"}
    )
    assert ok.status_code == 200 and ok.json() == {"jobs_run": 0}


# ------------------------------------------------------------------ rename / delete / permissions


async def test_delete_removes_search_data_immediately_and_file_later(
    make_user: UserFactory,
) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    [r] = await upload(alice, ws, ("a.pdf", make_pdf([LOREM * 5]), PDF_MIME))
    await drain()
    doc_id = r["document"]["id"]
    async with get_sessionmaker()() as db:
        key = (
            await db.execute(text("select storage_key from documents where id = :i"), {"i": doc_id})
        ).scalar_one()
    stored = Path(get_settings().storage_local_dir) / key
    assert stored.exists()

    assert (await alice.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}")).status_code == 204
    assert (
        await count(DocumentChunk, document_id=uuid.UUID(doc_id)) == 0
    )  # gone before the purge runs
    assert (await alice.get(f"/api/v1/workspaces/{ws}/documents/{doc_id}")).status_code == 404

    await drain()  # purge job
    assert not stored.exists()
    async with get_sessionmaker()() as db:
        assert (await db.execute(text("select count(*) from documents"))).scalar_one() == 0


async def test_edit_permissions(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com", "Owner")
    member = await make_user("member@example.com", "Member")
    viewer = await make_user("viewer@example.com", "Viewer")
    ws = (await owner.post("/api/v1/workspaces", json={"name": "Team"})).json()["id"]
    for client, role in ((member, "member"), (viewer, "viewer")):
        token = (
            await owner.post(f"/api/v1/workspaces/{ws}/invitations", json={"role": role})
        ).json()["token"]
        await client.post("/api/v1/invitations/accept", json={"token": token})

    [owners] = await upload(owner, ws, ("owner.txt", b"owner " + LOREM.encode(), "text/plain"))
    [members] = await upload(member, ws, ("member.txt", b"member " + LOREM.encode(), "text/plain"))
    docs = f"/api/v1/workspaces/{ws}/documents"

    # Viewers can read but not upload or change.
    r = await viewer.post(docs, files=[("files", ("v.txt", LOREM.encode(), "text/plain"))])
    assert r.status_code == 403
    assert (await viewer.get(docs)).json()["total"] == 2
    # Members edit their own uploads only.
    assert (
        await member.patch(f"{docs}/{members['document']['id']}", json={"title": "Mine"})
    ).status_code == 200
    assert (
        await member.patch(f"{docs}/{owners['document']['id']}", json={"title": "x"})
    ).status_code == 403
    assert (await member.delete(f"{docs}/{owners['document']['id']}")).status_code == 403
    listing = {d["title"]: d["can_edit"] for d in (await member.get(docs)).json()["items"]}
    assert listing == {"Mine": True, "owner": False}
    # Admins/owners edit anything.
    assert (await owner.delete(f"{docs}/{members['document']['id']}")).status_code == 204


# ------------------------------------------------------------------ collections


async def test_collections(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    a, b = await upload(
        alice,
        ws,
        ("a.txt", b"a " + LOREM.encode(), "text/plain"),
        ("b.txt", b"b " + LOREM.encode(), "text/plain"),
    )
    cols = f"/api/v1/workspaces/{ws}/collections"
    col = (await alice.post(cols, json={"name": "Contracts"})).json()
    assert (await alice.post(cols, json={"name": "contracts"})).status_code in (201, 409)

    ids = [a["document"]["id"], b["document"]["id"]]
    assert (await alice.put(f"{cols}/{col['id']}/documents", json={"document_ids": ids})).json()[
        "document_count"
    ] == 2
    # idempotent
    assert (
        await alice.put(f"{cols}/{col['id']}/documents", json={"document_ids": ids[:1]})
    ).json()["document_count"] == 2

    filtered = (
        await alice.get(f"/api/v1/workspaces/{ws}/documents", params={"collection_id": col["id"]})
    ).json()
    assert filtered["total"] == 2
    assert col["id"] in filtered["items"][0]["collection_ids"]

    removed = await alice.request(
        "DELETE", f"{cols}/{col['id']}/documents", json={"document_ids": ids[:1]}
    )
    assert removed.json()["document_count"] == 1
    # Deleting a collection keeps the documents.
    assert (await alice.delete(f"{cols}/{col['id']}")).status_code == 204
    assert (await alice.get(f"/api/v1/workspaces/{ws}/documents")).json()["total"] == 2


# ------------------------------------------------------------------ isolation


async def test_documents_are_isolated_between_workspaces(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    mallory = await make_user("mallory@example.com", "Mallory")
    ws_a = await personal_workspace_id(alice)
    ws_m = await personal_workspace_id(mallory)
    [r] = await upload(
        alice, ws_a, ("secret.pdf", make_pdf(["Top secret salary data. " + LOREM]), PDF_MIME)
    )
    await drain()
    doc = r["document"]["id"]

    # Through Alice's workspace id: not a member -> 404 everywhere.
    for method, url in [
        ("GET", f"/api/v1/workspaces/{ws_a}/documents"),
        ("GET", f"/api/v1/workspaces/{ws_a}/documents/{doc}"),
        ("GET", f"/api/v1/workspaces/{ws_a}/documents/{doc}/pages/1"),
        ("GET", f"/api/v1/workspaces/{ws_a}/documents/{doc}/download"),
        ("GET", f"/api/v1/workspaces/{ws_a}/documents/{doc}/file"),
        ("DELETE", f"/api/v1/workspaces/{ws_a}/documents/{doc}"),
    ]:
        assert (await mallory.request(method, url)).status_code == 404, url

    # Through Mallory's OWN workspace id with Alice's document id: still not found.
    for method, url in [
        ("GET", f"/api/v1/workspaces/{ws_m}/documents/{doc}"),
        ("GET", f"/api/v1/workspaces/{ws_m}/documents/{doc}/pages/1"),
        ("GET", f"/api/v1/workspaces/{ws_m}/documents/{doc}/file"),
        ("DELETE", f"/api/v1/workspaces/{ws_m}/documents/{doc}"),
    ]:
        assert (await mallory.request(method, url)).status_code == 404, url

    # ...and she can't pull it into her own collection.
    col = (
        await mallory.post(f"/api/v1/workspaces/{ws_m}/collections", json={"name": "Loot"})
    ).json()
    r2 = await mallory.put(
        f"/api/v1/workspaces/{ws_m}/collections/{col['id']}/documents", json={"document_ids": [doc]}
    )
    assert r2.status_code == 404
    assert (await get_doc(alice, ws_a, doc))["status"] == "ready"


async def test_deleting_a_workspace_purges_its_files(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = (await alice.post("/api/v1/workspaces", json={"name": "Temp"})).json()["id"]
    await upload(alice, ws, ("a.txt", b"x " + LOREM.encode(), "text/plain"))
    folder = Path(get_settings().storage_local_dir) / "ws" / ws
    assert folder.exists()
    assert (
        await alice.request("DELETE", f"/api/v1/workspaces/{ws}", json={"confirm_name": "Temp"})
    ).status_code == 204
    await drain()
    assert not folder.exists()
    assert get_storage() is not None
