"""Phase 6: semantic search, analytics, notifications, activity."""

from app.workers.maintenance import requeue_stale_embeddings
from app.workers.runner import drain
from tests.conftest import ApiClient, UserFactory, personal_workspace_id, user_id
from tests.files import make_pdf
from tests.test_rag import BENEFITS, NOTICE, ask, setup_ws

# ------------------------------------------------------------------ search


async def test_search_finds_passages_without_spending_questions(make_user: UserFactory) -> None:
    alice = await make_user()
    ws, [notice_doc, _] = await setup_ws(
        alice, ("Resignation.txt", NOTICE), ("Benefits.txt", BENEFITS)
    )
    r = await alice.post(
        f"/api/v1/workspaces/{ws}/search", json={"query": "written notice before resigning"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hybrid"
    top = body["hits"][0]
    assert top["document_id"] == notice_doc and top["document_title"] == "Resignation"
    assert top["file_type"] == "txt" and top["page_unit"] == "section"
    assert top["char_end"] > top["char_start"] >= 0 and "written notice" in top["text"]
    status = (await alice.get(f"/api/v1/workspaces/{ws}/ai/status")).json()
    assert status["questions_left_today"] == 30  # search is not a question


async def test_search_falls_back_to_keywords_without_ai_consent(make_user: UserFactory) -> None:
    alice = await make_user()
    ws, _ = await setup_ws(
        alice, ("Resignation.txt", NOTICE), ("Benefits.txt", BENEFITS), consent=False
    )
    body = (
        await alice.post(f"/api/v1/workspaces/{ws}/search", json={"query": "dependents"})
    ).json()
    assert body["mode"] == "keyword"
    assert [h["document_title"] for h in body["hits"]] == ["Benefits"]


async def test_search_stays_inside_the_workspace(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    mallory = await make_user("mallory@example.com", "Mallory")
    _, [secret] = await setup_ws(
        alice, ("Salaries.txt", "Confidential: the CEO salary is 9,000,000 per year.")
    )
    ws_m, _ = await setup_ws(mallory, ("Lunch.txt", "The canteen serves lunch from noon."))
    hits = (
        await mallory.post(f"/api/v1/workspaces/{ws_m}/search", json={"query": "CEO salary"})
    ).json()["hits"]
    assert all(h["document_id"] != secret for h in hits)
    scoped = await mallory.post(
        f"/api/v1/workspaces/{ws_m}/search",
        json={"query": "CEO salary", "scope": {"type": "documents", "ids": [secret]}},
    )
    assert scoped.status_code == 404


# ------------------------------------------------------------------ analytics & activity


async def _team(owner: ApiClient, member: ApiClient) -> str:
    ws = (await owner.post("/api/v1/workspaces", json={"name": "Team"})).json()["id"]
    token = (
        await owner.post(f"/api/v1/workspaces/{ws}/invitations", json={"role": "member"})
    ).json()["token"]
    await member.post("/api/v1/invitations/accept", json={"token": token})
    return str(ws)


async def test_analytics_for_admins_only(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com", "Owner")
    member = await make_user("member@example.com", "Member")
    ws = await _team(owner, member)
    await owner.post(f"/api/v1/workspaces/{ws}/ai-consent")
    files = [
        ("files", ("Resignation.txt", NOTICE.encode(), "text/plain")),
        (
            "files",
            (
                "Report.pdf",
                make_pdf(
                    [
                        "Quarterly report. Revenue grew 12 percent compared with the previous quarter."
                    ]
                ),
                "application/pdf",
            ),
        ),
    ]
    await member.post(f"/api/v1/workspaces/{ws}/documents", files=files)
    await drain()
    await ask(member, ws, "How many days notice do employees give?")
    await ask(member, ws, "quantum chromodynamics gluon")  # not found

    assert (await member.get(f"/api/v1/workspaces/{ws}/analytics")).status_code == 403
    r = await owner.get(f"/api/v1/workspaces/{ws}/analytics", params={"days": 7})
    assert r.status_code == 200, r.text
    a = r.json()
    t = a["totals"]
    assert (t["questions"], t["answered"], t["not_found"], t["failed"]) == (2, 1, 1, 0)
    assert t["input_tokens"] > 0 and isinstance(t["est_cost_usd"], float)
    assert (
        len(a["daily"]) == 7 and a["daily"][-1]["questions"] == 2
    )  # today, zeros filled for the rest
    assert sum(d["questions"] for d in a["daily"]) == 2
    ops = {o["operation"]: o for o in a["by_operation"]}
    assert {"chat", "embed_query", "embed_document"} <= set(ops)
    assert a["documents"] | {"by_type": None} == {
        "total": 2,
        "ready": 2,
        "processing": 0,
        "failed": 0,
        "storage_bytes": a["documents"]["storage_bytes"],
        "by_type": None,
        "uploads_in_range": 2,
    }
    assert a["documents"]["by_type"] == {"pdf": 1, "docx": 0, "txt": 1}
    assert a["top_members"] == [
        {"user_id": await user_id(member), "display_name": "Member", "questions": 2}
    ]


async def test_activity_feed_is_admin_only_and_paginated(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com", "Owner")
    member = await make_user("member@example.com", "Member")
    ws = await _team(owner, member)
    await member.post(
        f"/api/v1/workspaces/{ws}/documents",
        files=[("files", ("a.txt", NOTICE.encode(), "text/plain"))],
    )

    assert (await member.get(f"/api/v1/workspaces/{ws}/activity")).status_code == 403
    first = (await owner.get(f"/api/v1/workspaces/{ws}/activity", params={"limit": 2})).json()
    assert [i["action"] for i in first["items"]] == ["document.uploaded", "member.joined"]
    assert first["items"][0]["actor"] == "Member"
    rest = (
        await owner.get(
            f"/api/v1/workspaces/{ws}/activity", params={"before": first["next_before"]}
        )
    ).json()
    assert [i["action"] for i in rest["items"]] == ["invitation.created", "workspace.created"]
    assert rest["next_before"] is None


# ------------------------------------------------------------------ notifications


async def test_document_notifications_and_mark_read(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await personal_workspace_id(alice)
    await alice.post(
        f"/api/v1/workspaces/{ws}/documents",
        files=[
            ("files", ("Good.txt", NOTICE.encode(), "text/plain")),
            ("files", ("Scan.pdf", make_pdf(["", ""]), "application/pdf")),
        ],
    )
    await drain()
    data = (await alice.get("/api/v1/notifications")).json()
    assert data["unread"] == 2
    kinds = {n["type"]: n for n in data["items"]}
    assert kinds["document_ready"]["title"] == "“Good” is ready"
    assert kinds["document_ready"]["link"].startswith(f"/w/{ws}/documents?doc=")
    assert "OCR" in kinds["document_failed"]["body"]

    await alice.post("/api/v1/notifications/read", json={"ids": [kinds["document_ready"]["id"]]})
    assert (await alice.get("/api/v1/notifications")).json()["unread"] == 1
    await alice.post("/api/v1/notifications/read", json={})
    assert (await alice.get("/api/v1/notifications", params={"unread_only": True})).json() == {
        "items": [],
        "unread": 0,
    }


async def test_reembedding_does_not_notify_again(make_user: UserFactory) -> None:
    alice = await make_user()
    await setup_ws(alice, ("Resignation.txt", NOTICE))
    from sqlalchemy import text

    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as db:
        await db.execute(text("update documents set embedding_model = 'old-model@768'"))
        await db.commit()
    assert await requeue_stale_embeddings() == 1
    await drain()
    ready = [
        n
        for n in (await alice.get("/api/v1/notifications")).json()["items"]
        if n["type"] == "document_ready"
    ]
    assert len(ready) == 1


async def test_notifications_are_private(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    bob = await make_user("bob@example.com", "Bob")
    ws = await personal_workspace_id(alice)
    await alice.post(
        f"/api/v1/workspaces/{ws}/documents",
        files=[("files", ("a.txt", NOTICE.encode(), "text/plain"))],
    )
    await drain()
    alice_note = (await alice.get("/api/v1/notifications")).json()["items"][0]["id"]
    assert (await bob.get("/api/v1/notifications")).json() == {"items": [], "unread": 0}
    assert (await bob.post("/api/v1/notifications/read", json={"ids": [alice_note]})).json() == {
        "updated": 0
    }
    assert (await alice.get("/api/v1/notifications")).json()["unread"] == 1


async def test_email_invitation_can_be_accepted_from_the_notification(
    make_user: UserFactory,
) -> None:
    owner = await make_user("owner@example.com", "Owner")
    bob = await make_user("bob@example.com", "Bob")
    carol = await make_user("carol@example.com", "Carol")
    ws = (await owner.post("/api/v1/workspaces", json={"name": "Legal"})).json()["id"]
    await owner.post(
        f"/api/v1/workspaces/{ws}/invitations", json={"role": "viewer", "email": "bob@example.com"}
    )
    link_only = (
        await owner.post(f"/api/v1/workspaces/{ws}/invitations", json={"role": "member"})
    ).json()

    note = (await bob.get("/api/v1/notifications")).json()["items"][0]
    assert note["type"] == "invitation" and note["title"] == "Owner invited you to Legal"
    assert note["link"] is None and "token" not in str(
        note
    )  # never a usable secret in a notification

    # Someone else can't use Bob's invitation, and link-only invitations can't be accepted by id.
    assert (
        await carol.post(f"/api/v1/invitations/{note['invitation_id']}/accept")
    ).status_code == 404
    assert (await carol.post(f"/api/v1/invitations/{link_only['id']}/accept")).status_code == 404

    joined = await bob.post(f"/api/v1/invitations/{note['invitation_id']}/accept")
    assert joined.status_code == 200 and joined.json()["role"] == "viewer"
    assert (
        await bob.post(f"/api/v1/invitations/{note['invitation_id']}/accept")
    ).status_code == 404  # single use
    owner_note = (await owner.get("/api/v1/notifications")).json()["items"][0]
    assert owner_note["type"] == "member_joined" and owner_note["title"] == "Bob joined Legal"
