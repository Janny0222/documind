"""Tenant isolation: an outsider must not see or change anything in another workspace,
and the database itself must refuse cross-workspace links."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import get_engine
from tests.conftest import UserFactory, user_id

WS = "/api/v1/workspaces"


async def test_outsider_gets_404_on_every_workspace_route(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    mallory = await make_user("mallory@example.com", "Mallory")
    ws = (await alice.post(WS, json={"name": "Secret"})).json()["id"]
    alice_id = await user_id(alice)
    inv = (await alice.post(f"{WS}/{ws}/invitations", json={"role": "member"})).json()

    attempts = [
        ("GET", f"{WS}/{ws}", None),
        ("PATCH", f"{WS}/{ws}", {"name": "pwned"}),
        ("DELETE", f"{WS}/{ws}", {"confirm_name": "Secret"}),
        ("POST", f"{WS}/{ws}/ai-consent", None),
        ("POST", f"{WS}/{ws}/transfer-ownership", {"new_owner_id": alice_id}),
        ("GET", f"{WS}/{ws}/members", None),
        ("PATCH", f"{WS}/{ws}/members/{alice_id}", {"role": "viewer"}),
        ("DELETE", f"{WS}/{ws}/members/{alice_id}", None),
        ("GET", f"{WS}/{ws}/invitations", None),
        ("POST", f"{WS}/{ws}/invitations", {"role": "admin"}),
        ("DELETE", f"{WS}/{ws}/invitations/{inv['id']}", None),
    ]
    for method, url, body in attempts:
        r = await mallory.request(method, url, json=body)
        assert r.status_code == 404, f"{method} {url} -> {r.status_code}"

    # Nothing changed.
    assert (await alice.get(f"{WS}/{ws}")).json()["name"] == "Secret"
    assert ws not in {w["id"] for w in (await mallory.get(WS)).json()}


async def test_unknown_workspace_is_indistinguishable_from_forbidden(
    make_user: UserFactory,
) -> None:
    alice = await make_user()
    r = await alice.get(f"{WS}/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_invitation_ids_are_scoped_to_their_workspace(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    bob = await make_user("bob@example.com", "Bob")
    alice_ws = (await alice.post(WS, json={"name": "A"})).json()["id"]
    bob_ws = (await bob.post(WS, json={"name": "B"})).json()["id"]
    inv = (await alice.post(f"{WS}/{alice_ws}/invitations", json={"role": "member"})).json()

    # Bob is admin of *his* workspace but tries to revoke Alice's invitation through it.
    r = await bob.delete(f"{WS}/{bob_ws}/invitations/{inv['id']}")
    assert r.status_code == 404
    assert len((await alice.get(f"{WS}/{alice_ws}/invitations")).json()) == 1


async def _insert_document(conn, workspace_id: str) -> str:  # type: ignore[no-untyped-def]
    doc_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO documents (id, workspace_id, title, original_filename, mime_type, size_bytes,"
            " storage_key, sha256) VALUES (:id, :ws, 't', 't.txt', 'text/plain', 1, :key, :sha)"
        ),
        {"id": doc_id, "ws": workspace_id, "key": f"k/{doc_id}", "sha": doc_id.replace("-", "")},
    )
    return doc_id


async def test_database_rejects_cross_workspace_collection_links(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    bob = await make_user("bob@example.com", "Bob")
    ws_a = (await alice.get(WS)).json()[0]["id"]
    ws_b = (await bob.get(WS)).json()[0]["id"]

    async with get_engine().connect() as conn:
        doc_b = await _insert_document(conn, ws_b)
        col_a = str(uuid.uuid4())
        await conn.execute(
            text("INSERT INTO collections (id, workspace_id, name) VALUES (:id, :ws, 'c')"),
            {"id": col_a, "ws": ws_a},
        )
        # Link Alice's collection to Bob's document, claiming either workspace: both must fail.
        for claimed_ws in (ws_a, ws_b):
            # raises() outside the savepoint: the savepoint rolls back first, then we assert.
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO collection_documents (collection_id, document_id, workspace_id)"
                            " VALUES (:c, :d, :ws)"
                        ),
                        {"c": col_a, "d": doc_b, "ws": claimed_ws},
                    )
        await conn.rollback()


async def test_database_allows_exactly_one_owner(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    bob = await make_user("bob@example.com", "Bob")
    ws = (await alice.get(WS)).json()[0]["id"]
    async with get_engine().connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (:ws, :u, 'owner')"
                ),
                {"ws": ws, "u": await user_id(bob)},
            )
        await conn.rollback()
