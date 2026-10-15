"""Fernet-encrypted credentials in Postgres. Key: env LINEAGE_VAULT_KEY, else generated once into .vault.key.
Secrets are never returned by the API or logged."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

KEY_FILE = Path(__file__).resolve().parents[2] / ".vault.key"


def _fernet() -> Fernet:
    key = os.environ.get("LINEAGE_VAULT_KEY")
    if not key:
        if not KEY_FILE.exists():
            KEY_FILE.write_bytes(Fernet.generate_key())
        key = KEY_FILE.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


def norm_host(host: str | None) -> str:
    """'localhost' / '127.0.0.1' / '' -> '127.0.0.1:5432' style key."""
    h = (host or "127.0.0.1").strip().replace("localhost", "127.0.0.1")
    return h if ":" in h else f"{h}:5432"


def key(type_: str, host: str | None, database: str | None) -> tuple[str, str, str]:
    if type_ == "sqlite":
        return type_, "", os.path.normcase(os.path.abspath(database or ""))
    if type_ == "superset":
        return type_, (host or "").rstrip("/"), ""
    return type_, norm_host(host), database or ""


def put(conn, system: str, type_: str, host: str | None, database: str | None, secret: dict) -> None:
    t, h, d = key(type_, host, database)
    conn.execute(
        "INSERT INTO vault_credential (type, host, database, system, secret) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (type, host, database) DO UPDATE SET secret = EXCLUDED.secret, system = EXCLUDED.system, created_at = now()",
        (t, h, d, system, _fernet().encrypt(json.dumps(secret).encode())))


def get(conn, type_: str, host: str | None, database: str | None) -> dict | None:
    r = conn.execute("SELECT secret FROM vault_credential WHERE type=%s AND host=%s AND database=%s",
                     key(type_, host, database)).fetchone()
    return json.loads(_fernet().decrypt(bytes(r[0]))) if r else None


def find_sqlite(conn, hint: str) -> tuple[str, dict] | None:
    """A stored sqlite system whose path contains `hint` (OpenLineage dataset names carry only a fragment)."""
    for (path,) in conn.execute("SELECT database FROM vault_credential WHERE type='sqlite'").fetchall():
        if hint and hint.lower() in path.lower():
            return path, get(conn, "sqlite", None, path)
    return None


def same_host(conn, type_: str, host: str, database: str) -> list[tuple[str, dict]]:
    """Credentials stored for other databases (or ports) on the same host, most recent first."""
    h = norm_host(host)  # any port on the same host
    rows = conn.execute("SELECT system, secret FROM vault_credential WHERE type=%s AND split_part(host, ':', 1) = %s "
                        "AND NOT (host = %s AND database = %s) ORDER BY created_at DESC",
                        (type_, h.split(":")[0], h, database)).fetchall()
    return [(s, json.loads(_fernet().decrypt(bytes(b)))) for s, b in rows]


def systems(conn) -> list[dict]:
    return [{"system": s, "type": t, "host": h, "database": d}
            for t, h, d, s in conn.execute("SELECT type, host, database, system FROM vault_credential ORDER BY created_at")]


def delete(conn, system: str | None = None) -> int:
    """Remove one system's credentials, or all of them."""
    return conn.execute("DELETE FROM vault_credential WHERE %s::text IS NULL OR system = %s", (system, system)).rowcount
