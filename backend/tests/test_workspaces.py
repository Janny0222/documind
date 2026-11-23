from app.core.config import get_settings
from tests.conftest import ApiClient, UserFactory, personal_workspace_id, user_id

WS = "/api/v1/workspaces"


async def _team(owner: ApiClient, name: str = "Acme") -> str:
    r = await owner.post(WS, json={"name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _join(owner: ApiClient, ws: str, member: ApiClient, role: str = "member") -> None:
    r = await owner.post(f"{WS}/{ws}/invitations", json={"role": role})
    assert r.status_code == 201, r.text
    r = await member.post("/api/v1/invitations/accept", json={"token": r.json()["token"]})
    assert r.status_code == 200, r.text


async def test_create_list_rename(make_user: UserFactory) -> None:
    alice = await make_user()
    ws = await _team(alice, "Acme")
    names = {w["name"] for w in (await alice.get(WS)).json()}
    assert names == {"Alice's Workspace", "Acme"}

    r = await alice.patch(f"{WS}/{ws}", json={"name": "Acme Corp"})
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Corp"


async def test_workspace_limit(make_user: UserFactory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "max_owned_workspaces", 2)  # personal + 1
    alice = await make_user()
    await _team(alice, "One")
    r = await alice.post(WS, json={"name": "Two"})
    assert r.status_code == 409
    assert r.json()["code"] == "workspace_limit"


async def test_invitation_flow(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com", "Alice")
    bob = await make_user("bob@example.com", "Bob")
    ws = await _team(alice)

    created = (await alice.post(f"{WS}/{ws}/invitations", json={"role": "viewer"})).json()
    assert created["invite_url"].endswith(created["token"])

    preview = await bob.post("/api/v1/invitations/preview", json={"token": created["token"]})
    assert preview.status_code == 200
    assert preview.json()["workspace_name"] == "Acme"
    assert preview.json()["invited_by"] == "Alice"

    accepted = await bob.post("/api/v1/invitations/accept", json={"token": created["token"]})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "viewer"

    members = {m["email"]: m["role"] for m in (await alice.get(f"{WS}/{ws}/members")).json()}
    assert members == {"alice@example.com": "owner", "bob@example.com": "viewer"}

    again = await bob.post("/api/v1/invitations/accept", json={"token": created["token"]})
    assert again.status_code == 404  # single use


async def test_email_bound_invitation_rejects_other_users(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com")
    carol = await make_user("carol@example.com", "Carol")
    ws = await _team(alice)
    token = (
        await alice.post(
            f"{WS}/{ws}/invitations", json={"role": "member", "email": "bob@example.com"}
        )
    ).json()["token"]
    r = await carol.post("/api/v1/invitations/accept", json={"token": token})
    assert r.status_code == 404


async def test_revoked_invitation_cannot_be_used(make_user: UserFactory) -> None:
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com", "Bob")
    ws = await _team(alice)
    inv = (await alice.post(f"{WS}/{ws}/invitations", json={"role": "member"})).json()
    assert (await alice.delete(f"{WS}/{ws}/invitations/{inv['id']}")).status_code == 204
    assert (
        await bob.post("/api/v1/invitations/accept", json={"token": inv["token"]})
    ).status_code == 404
    assert (await alice.get(f"{WS}/{ws}/invitations")).json() == []


async def test_role_permissions(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com", "Owner")
    admin = await make_user("admin@example.com", "Admin")
    admin2 = await make_user("admin2@example.com", "Admin2")
    member = await make_user("member@example.com", "Member")
    viewer = await make_user("viewer@example.com", "Viewer")
    ws = await _team(owner)
    await _join(owner, ws, admin, "admin")
    await _join(owner, ws, admin2, "admin")
    await _join(owner, ws, member, "member")
    await _join(owner, ws, viewer, "viewer")
    admin2_id, member_id, viewer_id = (
        await user_id(admin2),
        await user_id(member),
        await user_id(viewer),
    )
    owner_id = await user_id(owner)

    # Viewers and members can read but not administer.
    assert (await viewer.get(f"{WS}/{ws}/members")).status_code == 200
    for client in (viewer, member):
        assert (await client.patch(f"{WS}/{ws}", json={"name": "X"})).status_code == 403
        assert (
            await client.post(f"{WS}/{ws}/invitations", json={"role": "member"})
        ).status_code == 403
        assert (
            await client.delete(f"{WS}/{ws}/members/{viewer_id if client is member else member_id}")
        ).status_code == 403

    # Admins manage members/viewers but not admins or the owner, and can't mint admins.
    assert (
        await admin.patch(f"{WS}/{ws}/members/{viewer_id}", json={"role": "member"})
    ).status_code == 200
    assert (
        await admin.patch(f"{WS}/{ws}/members/{viewer_id}", json={"role": "admin"})
    ).status_code == 403
    assert (
        await admin.patch(f"{WS}/{ws}/members/{admin2_id}", json={"role": "member"})
    ).status_code == 403
    assert (
        await admin.patch(f"{WS}/{ws}/members/{owner_id}", json={"role": "member"})
    ).status_code == 403
    assert (await admin.post(f"{WS}/{ws}/invitations", json={"role": "admin"})).status_code == 403
    assert (await admin.delete(f"{WS}/{ws}/members/{admin2_id}")).status_code == 403

    # Only the owner deletes the workspace.
    assert (
        await admin.request("DELETE", f"{WS}/{ws}", json={"confirm_name": "Acme"})
    ).status_code == 403

    # Owner can do all of it.
    assert (
        await owner.patch(f"{WS}/{ws}/members/{admin2_id}", json={"role": "viewer"})
    ).status_code == 200
    assert (await owner.delete(f"{WS}/{ws}/members/{member_id}")).status_code == 204
    assert (await member.get(f"{WS}/{ws}")).status_code == 404  # removed => no access


async def test_cannot_change_own_role(make_user: UserFactory) -> None:
    owner = await make_user()
    ws = await _team(owner)
    r = await owner.patch(f"{WS}/{ws}/members/{await user_id(owner)}", json={"role": "admin"})
    assert r.status_code == 403


async def test_leave_workspace(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com")
    bob = await make_user("bob@example.com", "Bob")
    ws = await _team(owner)
    await _join(owner, ws, bob)

    r = await owner.delete(f"{WS}/{ws}/members/{await user_id(owner)}")
    assert r.status_code == 409
    assert r.json()["code"] == "owner_cannot_leave"

    assert (await bob.delete(f"{WS}/{ws}/members/{await user_id(bob)}")).status_code == 204
    assert (await bob.get(f"{WS}/{ws}")).status_code == 404


async def test_transfer_ownership(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com")
    bob = await make_user("bob@example.com", "Bob")
    ws = await _team(owner)
    await _join(owner, ws, bob)

    r = await owner.post(f"{WS}/{ws}/transfer-ownership", json={"new_owner_id": await user_id(bob)})
    assert r.status_code == 204
    roles = {m["email"]: m["role"] for m in (await bob.get(f"{WS}/{ws}/members")).json()}
    assert roles == {"owner@example.com": "admin", "bob@example.com": "owner"}


async def test_delete_workspace(make_user: UserFactory) -> None:
    owner = await make_user()
    ws = await _team(owner, "Acme")
    personal = await personal_workspace_id(owner)

    r = await owner.request("DELETE", f"{WS}/{ws}", json={"confirm_name": "acme"})
    assert r.status_code == 422
    assert (
        await owner.request("DELETE", f"{WS}/{ws}", json={"confirm_name": "Acme"})
    ).status_code == 204
    assert (await owner.get(f"{WS}/{ws}")).status_code == 404

    r = await owner.request(
        "DELETE", f"{WS}/{personal}", json={"confirm_name": "Alice's Workspace"}
    )
    assert r.status_code == 409


async def test_ai_consent_requires_admin(make_user: UserFactory) -> None:
    owner = await make_user("owner@example.com")
    bob = await make_user("bob@example.com", "Bob")
    ws = await _team(owner)
    await _join(owner, ws, bob)
    assert (await bob.post(f"{WS}/{ws}/ai-consent")).status_code == 403
    r = await owner.post(f"{WS}/{ws}/ai-consent")
    assert r.status_code == 200
    assert r.json()["ai_consent"] is True
