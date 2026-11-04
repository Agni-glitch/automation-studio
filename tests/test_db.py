import asyncio
import sqlite3
import sys

import pytest

from database import Database, DpapiKeyStore, StaticKeyStore, VaultError
from engine import WorkflowDefinition, WorkflowEngine
from engine.errors import CredentialNotFoundError


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "t.db", key_store=StaticKeyStore()) as database:
        yield database


def test_workflow_crud(db):
    wf = WorkflowDefinition(name="A", nodes=[{"id": "s", "type": "trigger.manual"}])
    db.save_workflow(wf)
    wf.name = "A2"
    db.save_workflow(wf, active=True)
    assert db.get_workflow(wf.id).name == "A2"
    [row] = db.list_workflows()
    assert row["active"] is True and row["name"] == "A2"
    assert db.delete_workflow(wf.id) and db.get_workflow(wf.id) is None


def test_credentials_encrypted_at_rest(db, tmp_path):
    db.set_credential("openai", {"api_key": "sk-very-secret-value"}, type="api_key")
    assert asyncio.run(db.get_credential("openai")) == {"api_key": "sk-very-secret-value"}
    assert db.list_credentials()[0]["fields"] == ["api_key"]

    raw = sqlite3.connect(tmp_path / "t.db").execute("SELECT data FROM credentials").fetchone()[0]
    assert b"sk-very-secret-value" not in raw

    with pytest.raises(CredentialNotFoundError):
        db.get_credential_sync("missing")
    assert db.delete_credential("openai")


def test_wrong_key_cannot_decrypt(tmp_path):
    with Database(tmp_path / "k.db", key_store=StaticKeyStore()) as d:
        d.set_credential("x", {"a": "secret"})
    with Database(tmp_path / "k.db", key_store=StaticKeyStore()) as d, pytest.raises(VaultError):
        d.get_credential_sync("x")


def test_execution_history_with_engine(db):
    db.set_credential("k", {"api_key": "abcd1234"})
    engine = WorkflowEngine(credentials=db)
    wf = WorkflowDefinition(name="H", nodes=[{"id": "s", "type": "trigger.manual"}])
    for _ in range(3):
        db.save_execution(asyncio.run(engine.run(wf, trigger_data={"x": 1})))
    history = db.list_executions(wf.id)
    assert len(history) == 3 and history[0]["status"] == "success"
    assert db.get_execution(history[0]["id"]).output_of("s") == {"x": 1}
    assert db.prune_executions(keep_per_workflow=1) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_key_store_roundtrip(tmp_path):
    with Database(tmp_path / "d.db") as d:
        d.set_credential("x", {"a": "secret"})
    key_file = tmp_path / "d.key"
    assert key_file.exists() and len(key_file.read_bytes()) > 100  # DPAPI blob, not a raw key
    with Database(tmp_path / "d.db") as d:
        assert d.get_credential_sync("x") == {"a": "secret"}
    assert DpapiKeyStore(key_file).load_or_create() == DpapiKeyStore(key_file).load_or_create()
