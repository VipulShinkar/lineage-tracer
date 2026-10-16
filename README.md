# lineage-tracer

Discovers column-level regulatory data lineage from BI reports down to systems of record, with reconciliation evidence (BCBS 239).

Upload a report (PDF, XBRL, XLSX), pick a value, and the tracer walks it back through BI datasets, SQL views and warehouse tables to the source systems, reconciling each hop. SQL lineage comes from the built-in SQL/XML lineage parser (sqlglot for SQL; SSIS, Informatica and generic XML). Results are stored in PostgreSQL + Apache AGE and shown in a React UI.

Architecture, components and decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start (Windows 11 + WSL2)

Requires WSL2 Ubuntu with PostgreSQL + Apache AGE (see ARCHITECTURE section 7), `uv`, Node.js. The sandbox setup installs Apache Spark (PySpark) inside WSL for the Spark pipeline.

```powershell
uv venv
uv pip install -e ".[dev]"
powershell -File scripts/db.ps1                      # start Postgres (WSL)
powershell -File sandbox/setup.ps1                   # one-off: demo estate + lake + Superset + pipelines (shell LCR, Informatica C90, PySpark EFR)
.venv\Scripts\python -m lineage_store.seed --reset   # Explorer seed data
.venv\Scripts\uvicorn lineage_api.app:app --host 127.0.0.1 --port 8000
cd web; npm ci; npx vite --host 127.0.0.1            # http://127.0.0.1:5173
.venv\Scripts\pytest -q                              # test suite
```

Use `127.0.0.1`, not `localhost`. Demo walkthrough: [sandbox/README.md](sandbox/README.md).

## Sandbox

The `sandbox/` demo estate uses fixed passwords (e.g. `admin/admin`, `lineage_ro/lineage_ro`). They are local development credentials only; never reuse them.

## License

MIT, see [LICENSE](LICENSE).
