

def test_concurrent_registrations_in_one_root_are_not_lost(tmp_path, monkeypatch):
    """Two sessions registering models in the same root used to race on the
    read-modify-write of the registry JSON and drop a registration (R4.3)."""
    import threading
    import time

    from groundwater_mcp.utils import workspace as ws

    root = tmp_path / "root"
    real_load = ws._load_registry

    def slow_load(workspace_root):
        data = real_load(workspace_root)
        time.sleep(0.05)  # widen the read -> write window
        return data

    monkeypatch.setattr(ws, "_load_registry", slow_load)
    monkeypatch.setattr(ws, "_known_roots_path", lambda: tmp_path / "known_roots.json")

    names = [f"m{i}" for i in range(6)]
    errors: list[Exception] = []

    def register(name):
        try:
            ws.create_workspace(name, str(root / name))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=register, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert set(real_load(root)) == set(names)


def test_stale_registry_lock_is_taken_over(tmp_path):
    import os

    from groundwater_mcp.utils import workspace as ws

    root = tmp_path / "root"
    root.mkdir()
    lock = root / ".gwmcp_registry.lock"
    lock.write_text("")
    old = lock.stat().st_mtime - 3600
    os.utime(lock, (old, old))
    with ws._registry_lock(root):
        assert lock.exists()
    assert not lock.exists()


def test_stale_default_registration_does_not_shadow_a_new_workspace(tmp_path, monkeypatch):
    """A registry entry whose directory no longer exists (an old session, a
    deleted worktree) must not hijack a model created later under the same
    name in another root — the worked-example bug: ``catchment`` resolved to a
    deleted holdout path and ``set_simulation`` failed there."""
    import json

    from groundwater_mcp.utils import workspace as ws

    default_root = tmp_path / "default"
    default_root.mkdir()
    monkeypatch.setattr(ws, "default_workspace_root", lambda: default_root)
    (default_root / ".gwmcp_registry.json").write_text(
        json.dumps({"catchment": str(tmp_path / "gone" / "catchment")})
    )

    created = ws.create_workspace("catchment", str(tmp_path / "work" / "catchment"))
    assert ws.resolve_workspace("catchment") == created
    assert ws.list_workspaces()["catchment"] == str(created)


def test_stale_registration_alone_still_resolves(tmp_path, monkeypatch):
    """With nothing else to prefer, the registered path is still returned (the
    tool then reports the missing files rather than 'no such model')."""
    import json

    from groundwater_mcp.utils import workspace as ws

    default_root = tmp_path / "default"
    default_root.mkdir()
    monkeypatch.setattr(ws, "default_workspace_root", lambda: default_root)
    gone = tmp_path / "gone" / "m"
    (default_root / ".gwmcp_registry.json").write_text(json.dumps({"m": str(gone)}))
    assert ws.resolve_workspace("m") == gone
