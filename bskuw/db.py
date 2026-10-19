"""One DuckDB file for the local app. The connection is process-wide."""

import os
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb

from bskuw.paths import DB_PATH, PROJECT_DB_PATH

_LOCK = threading.RLock()
_CONNECTION = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracking (
    year_week VARCHAR,
    basket VARCHAR,
    product_bs VARCHAR,
    sku VARCHAR,
    stock_qty_w DOUBLE,
    source_file VARCHAR
);

CREATE TABLE IF NOT EXISTS sku_dim (
    sku VARCHAR,
    name VARCHAR,
    brand VARCHAR,
    model VARCHAR,
    size VARCHAR,
    tread VARCHAR,
    condition VARCHAR,
    internal_category VARCHAR,
    majority VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS wholesale (
    sku VARCHAR,
    sale_date DATE,
    sale_number VARCHAR,
    source_file VARCHAR
);

CREATE TABLE IF NOT EXISTS quant_report (
    source_file VARCHAR,
    last_sale_date DATE
);
"""

_WHOLESALE_TABLE = """
CREATE TABLE wholesale (
    sku VARCHAR,
    sale_date DATE,
    sale_number VARCHAR,
    source_file VARCHAR
)
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tracking_week_basket ON tracking (year_week, basket);
CREATE INDEX IF NOT EXISTS idx_sku_dim_sku ON sku_dim (sku);
CREATE INDEX IF NOT EXISTS idx_wholesale_sku ON wholesale (sku);
CREATE INDEX IF NOT EXISTS idx_wholesale_sale_date ON wholesale (sale_date);
"""

# Ambiguous slash dates are day/month/year. A month/day value is tried only
# when the day/month reading is impossible (for example 05/13/2026).
_PARSE_MACRO = """
CREATE OR REPLACE MACRO parse_sale_date(text) AS
CAST(
    COALESCE(
        TRY_STRPTIME(text, '%Y-%m-%d'),
        TRY_STRPTIME(text, '%Y-%m-%d %H:%M:%S'),
        TRY_STRPTIME(text, '%d/%m/%Y'),
        TRY_STRPTIME(text, '%d/%m/%Y %H:%M:%S'),
        TRY_STRPTIME(text, '%d.%m.%Y'),
        TRY_STRPTIME(text, '%d.%m.%Y %H:%M:%S'),
        TRY_STRPTIME(text, '%d-%m-%Y'),
        TRY_STRPTIME(text, '%Y/%m/%d'),
        TRY_STRPTIME(text, '%m/%d/%Y'),
        TRY_STRPTIME(text, '%m/%d/%Y %H:%M:%S')
    ) AS DATE
)
"""


def get_connection():
    """Return the shared DuckDB connection, creating the schema on first use."""
    global _CONNECTION
    with _LOCK:
        if _CONNECTION is None:
            _adopt_project_database()
            try:
                _CONNECTION = _open_database(DB_PATH)
            except duckdb.Error:
                wal = Path(str(DB_PATH) + ".wal")
                if not wal.is_file():
                    raise
                wal.unlink()
                _CONNECTION = _open_database(DB_PATH)
        return _CONNECTION


def export_snapshot():
    """Write a consistent copy of the open database and return that file."""
    connection = get_connection()
    snapshot = DB_PATH.with_name("bskuw-snapshot.duckdb")
    with _LOCK:
        connection.execute("CHECKPOINT")
        _remove_database_files(snapshot)
        connection.execute("ATTACH '{path}' AS bskuw_snapshot".format(path=_sql_path(snapshot)))
        source = connection.execute(
            """
            SELECT database_name
            FROM duckdb_databases()
            WHERE internal = false AND database_name <> 'bskuw_snapshot'
            """
        ).fetchone()[0]
        try:
            connection.execute(
                "COPY FROM DATABASE {source} TO bskuw_snapshot".format(source=_quote_ident(source))
            )
        finally:
            connection.execute("DETACH bskuw_snapshot")
    return snapshot


def replace_database(payload):
    """Close the open database and open this uploaded DuckDB file instead."""
    if not _is_duckdb_payload(payload):
        raise ValueError("This file is not a DuckDB database.")
    incoming = DB_PATH.with_name("bskuw-upload.duckdb")
    with _LOCK:
        _close_connection()
        _remove_database_files(incoming)
        incoming.write_bytes(payload)
        probe = None
        try:
            probe = duckdb.connect(str(incoming))
            probe.execute("SELECT 1")
            probe.close()
            probe = None
        except Exception as exc:
            if probe is not None:
                probe.close()
            _remove_database_files(incoming)
            _open_if_present()
            raise ValueError("This database file could not be opened.") from exc
        try:
            incoming.replace(DB_PATH)
        except OSError as exc:
            _open_if_present()
            raise ValueError(
                "The current database file is still open in another program. Close it and try the upload again."
            ) from exc
        _remove_database_files(Path(str(DB_PATH) + ".wal"))
        _CONNECTION = _open_database(DB_PATH)


def _open_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    connection.execute("SET enable_progress_bar = false")
    _ensure_schema(connection)
    return connection


def _adopt_project_database():
    """Copy data/bskuw.duckdb into the local folder when that folder has no database yet.

    A shared read succeeds while Google Drive has the project file open. DuckDB
    itself refuses to open that locked file.
    """
    if DB_PATH.is_file() or not PROJECT_DB_PATH.is_file():
        return
    if PROJECT_DB_PATH.resolve() == DB_PATH.resolve():
        return
    temporary = DB_PATH.with_name("bskuw-migrate.duckdb")
    _remove_database_files(temporary)
    try:
        _copy_shared(PROJECT_DB_PATH, temporary)
        wal = Path(str(PROJECT_DB_PATH) + ".wal")
        if wal.is_file():
            _copy_shared(wal, Path(str(temporary) + ".wal"))
        temporary.replace(DB_PATH)
        migrated_wal = Path(str(temporary) + ".wal")
        if migrated_wal.is_file():
            migrated_wal.replace(Path(str(DB_PATH) + ".wal"))
    except OSError:
        _remove_database_files(temporary)
        raise


def _copy_shared(source, destination):
    """Copy a file even when another process, such as Google Drive, has it open."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        destination.write_bytes(source.read_bytes())
        return
    import ctypes
    from ctypes import wintypes

    generic_read = 0x80000000
    share_all = 0x1 | 0x2 | 0x4
    open_existing = 3
    normal = 0x80
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(
        str(source), generic_read, share_all, None, open_existing, normal, None
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "Cannot read {0}".format(source))
    buffer = ctypes.create_string_buffer(1024 * 1024)
    read = wintypes.DWORD()
    try:
        with destination.open("wb") as output:
            while True:
                ok = kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None)
                if not ok:
                    raise OSError(ctypes.get_last_error(), "Cannot read {0}".format(source))
                if read.value == 0:
                    break
                output.write(buffer.raw[: read.value])
    finally:
        kernel32.CloseHandle(handle)


def _open_if_present():
    """Reopen the live database after a failed swap, when that file is still there."""
    global _CONNECTION
    if _CONNECTION is None and DB_PATH.is_file():
        _CONNECTION = _open_database(DB_PATH)


def _close_connection():
    global _CONNECTION
    if _CONNECTION is not None:
        _CONNECTION.close()
        _CONNECTION = None


def _remove_database_files(path):
    """Delete a database file. A path ending in .wal deletes only that file."""
    if path.suffix == ".wal":
        if path.is_file():
            path.unlink()
        return
    if path.is_file():
        path.unlink()
    wal = Path(str(path) + ".wal")
    if wal.is_file():
        wal.unlink()


def _sql_path(path):
    return str(path).replace("\\", "/").replace("'", "''")


def _is_duckdb_payload(payload):
    return bool(payload) and b"DUCK" in payload[:32]


def _quote_ident(name):
    return '"{name}"'.format(name=name.replace('"', '""'))


def _ensure_schema(connection):
    connection.execute(_SCHEMA)
    columns = [row[0] for row in connection.execute("DESCRIBE wholesale").fetchall()]
    if "sale_date" not in columns:
        connection.execute("DROP TABLE wholesale")
        connection.execute(_WHOLESALE_TABLE)
    connection.execute(_INDEXES)
    connection.execute(_PARSE_MACRO)


def ensure_quant_report():
    """Create the one-row quant report table on connections opened before it existed."""
    connection = get_connection()
    with _LOCK:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quant_report (
                source_file VARCHAR,
                last_sale_date DATE
            )
            """
        )


def execute(sql, params=None):
    connection = get_connection()
    with _LOCK:
        if params:
            return connection.execute(sql, params)
        return connection.execute(sql)


def executemany(sql, rows):
    connection = get_connection()
    with _LOCK:
        return connection.executemany(sql, rows)


@contextmanager
def transaction():
    """Run a block as one DuckDB transaction."""
    connection = get_connection()
    with _LOCK:
        connection.execute("BEGIN TRANSACTION")
        try:
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def fetchall(sql, params=None):
    connection = get_connection()
    with _LOCK:
        cursor = connection.execute(sql, params) if params else connection.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
    return columns, rows


def fetch_dicts(sql, params=None):
    columns, rows = fetchall(sql, params)
    return [dict(zip(columns, row)) for row in rows]


def fetch_one(sql, params=None):
    connection = get_connection()
    with _LOCK:
        cursor = connection.execute(sql, params) if params else connection.execute(sql)
        return cursor.fetchone()
