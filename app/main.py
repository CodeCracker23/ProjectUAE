"""
Main FastAPI application for the CSV (SOH) processor.

This app:
- accepts CSV uploads,
- writes CSV files to local disk,
- stores metadata in SQLite,
- optionally uploads to S3,
- serves a small HTML UI to view/download files,
- exposes JSON endpoints and a health check for Kubernetes.
"""

# -----------------------
# Standard library imports
# -----------------------

import csv
# csv: provides reader/writer utilities to parse CSV text into Python lists.
# In this app we use csv.reader() to split uploaded CSV content into header + rows.

import os
# os: environment and filesystem utilities. We use os.getenv() to read configuration
# (S3 bucket name, DB path, log level, etc.) so the app is configurable via env vars.

import uuid
# uuid: used to generate unique IDs for uploaded files (UUID4), avoiding collisions
# and allowing predictable file naming like "<uuid>.csv".

import sqlite3
# sqlite3: lightweight file-based relational database used to persist metadata (not file blobs).
# The DB file lives on disk (e.g., processed_files.db) and survives restarts when backed by PVC.

import logging
# logging: standard logging module. We configure it to help debug and monitor the app.

from datetime import datetime
# datetime: used to timestamp uploads (uploaded_at) and to create date prefixes for S3 keys.

from pathlib import Path
# pathlib.Path: modern filesystem paths; used to create LOCAL_STORAGE directory and manage file paths.

from typing import List, Optional
# typing: used for type hints (List, Optional) to make the code clearer and aid tools/IDE.

# -----------------------
# Third-party imports
# -----------------------

import boto3
# boto3: AWS SDK for Python. We use the S3 client to optionally upload stored CSV files to S3.
# The app is designed to skip S3 uploads gracefully if credentials are not present.

from botocore.exceptions import NoCredentialsError, PartialCredentialsError
# Exceptions from botocore used to detect credential-related upload failures and handle them cleanly.

from fastapi import FastAPI, UploadFile, File, HTTPException
# fastapi: core web framework used to define routes, handle file uploads, and return responses.
# UploadFile lets FastAPI stream uploaded file contents efficiently.

from fastapi.responses import HTMLResponse, FileResponse
# HTMLResponse: render simple HTML pages (our UI).
# FileResponse: stream a file back to the client for download (returns correct headers).

from fastapi.staticfiles import StaticFiles
# StaticFiles: mount and serve static assets (CSS/JS) when running locally for dev convenience.

from pydantic import BaseModel
# pydantic: used to define typed models (ProcessedFile). Ensures metadata objects are well-formed.

from jinja2 import Template
# jinja2.Template: tiny templating engine to render HTML pages (we use simple templates embedded
# in the code for index + file view).

# -----------------------
# Configuration (env-driven)
# -----------------------

S3_BUCKET = os.getenv("S3_BUCKET", "soh-files-bucket")
# S3_BUCKET: destination bucket name for optional S3 backups. Default is a sensible placeholder.

S3_REGION = os.getenv("AWS_REGION", "us-east-1")
# AWS_REGION: region for the S3 client. Not critical locally, but useful in real AWS setups.

LOCAL_STORAGE = Path(os.getenv("LOCAL_STORAGE", "./data"))
# LOCAL_STORAGE: on-disk folder where the uploaded CSVs get written. Using a separate folder
# makes it simple to mount a PVC to persist files in Kubernetes.

LOCAL_STORAGE.mkdir(parents=True, exist_ok=True)
# Ensure the folder exists at startup. If running in Kubernetes, mount your PVC to this path
# (or set LOCAL_STORAGE to the mount path). Files written here are the physical copies.

# -----------------------
# Logging setup
# -----------------------

logger = logging.getLogger("soh-app")
# get a named logger for the app; helps filter/identify logs in aggregated systems

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s %(levelname)s %(message)s'
)
# Configure basic logging format and the log level via LOG_LEVEL env var (default INFO).

# -----------------------
# S3 helpers and client
# -----------------------

def has_aws_credentials() -> bool:
    """
    Check whether AWS credentials are available via environment variables.
    This is a simple check used to decide whether to attempt S3 uploads.
    """
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))

try:
    # Create an S3 client. If boto3 can't find config/credentials it may still succeed;
    # however, we still guard uploads with has_aws_credentials().
    s3_client = boto3.client("s3", region_name=S3_REGION)
except Exception as e:
    # If client initialization fails for any reason, warn (but keep app running).
    logger.warning("Failed to create S3 client: %s", e)
    s3_client = None

# -----------------------
# FastAPI app & static mount
# -----------------------

app = FastAPI(title="SOH CSV Processor")
# Create the FastAPI application instance. All routes are defined on this object.

# Mount the "static" directory if it exists so local dev can serve CSS/JS files.
# In production (Kubernetes), you might instead have an Nginx sidecar serve the same folder
# from a shared PVC. This mount is purely for developer convenience.
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# -----------------------
# HTML templates (very small)
# -----------------------

INDEX_TEMPLATE = Template("""
<!doctype html>
<html><head><title>SOH Processor</title><link rel="stylesheet" href="/static/style.css" /></head>
<body>
<h1>Upload CSV</h1>
<form action="/upload" method="post" enctype="multipart/form-data">
<input type="file" name="file" accept=".csv" required />
<button type="submit">Upload</button>
</form>
<h2>Processed Files</h2>
<ul>
{% for f in files %}
<li><a href="/file/{{ f['id'] }}">{{ f['original_name'] }} ({{ f['rows'] }} rows)</a> - {{ f['uploaded_at'] }}</li>
{% endfor %}
</ul>
</body></html>
""")
# INDEX_TEMPLATE: very small Jinja template that renders an upload form and a list of files.
# It uses the metadata from the DB (id, original_name, rows, uploaded_at) to populate the list.

FILE_TEMPLATE = Template("""
<!doctype html>
<html><head><title>{{ file.original_name }}</title></head><body>
<h1>{{ file.original_name }}</h1>
<table border="1" cellpadding="4">
<thead><tr>{% for h in file.headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
<tbody>
{% for row in file.rows %}
<tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
{% endfor %}
</tbody></table>
<p><a href="/">Back</a></p>
</body></html>
""")
# FILE_TEMPLATE: renders a CSV preview table (headers + rows). Used after upload and on the file view route.

# -----------------------
# Data model for metadata
# -----------------------

class ProcessedFile(BaseModel):
    """
    Pydantic model representing stored metadata for an uploaded CSV file.
    - id: UUID string used as the primary identifier.
    - path: local filesystem path where the CSV was saved (LOCAL_STORAGE/<uuid>.csv).
    - original_name: original filename provided by the uploader (for display/download).
    - rows: number of data rows (header excluded).
    - headers: list of column names parsed from the CSV header row.
    - uploaded_at: UTC timestamp when the upload occurred.
    """
    id: str
    path: Path
    original_name: str
    rows: int
    headers: List[str]
    uploaded_at: datetime

# processed_index: optional in-memory list. The real source of truth is SQLite (see DB below).
processed_index: List[ProcessedFile] = []

# -----------------------
# SQLite persistence setup
# -----------------------

DB_PATH = os.getenv("DB_PATH", "processed_files.db")
# DB_PATH: file path for the SQLite database. Default "processed_files.db" means
# it will be created in the current working directory. To persist across pod restarts,
# mount a PVC at the working dir or set DB_PATH to a path on the PVC.

# Creating a connection to SQLite will create the DB file if it doesn't exist.
# check_same_thread=False allows the DB connection to be used by different threads
# that FastAPI / Uvicorn may spawn. For higher concurrency or production use,
# consider using a real DB (Postgres) or connection pool.
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

# Create the 'processed_files' table if it does not already exist.
# fields:
#  - id: primary key (text)
#  - path: local file path stored as text
#  - original_name: original uploaded filename
#  - rows: integer row count excluding header
#  - headers: headers stored as a single string separated by '|'
#  - uploaded_at: ISO-formatted UTC timestamp as text
conn.execute("""CREATE TABLE IF NOT EXISTS processed_files (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    rows INTEGER NOT NULL,
    headers TEXT,
    uploaded_at TEXT NOT NULL
)""")
conn.commit()
# The commit persists the schema change. After this, DB operations can be performed.

# -----------------------
# Database helper functions
# -----------------------

def db_add(pf: ProcessedFile):
    """
    Insert a ProcessedFile record into the SQLite DB.
    - Stores headers as a single pipe-separated string to keep the schema simple.
    - uploaded_at is stored as an ISO timestamp string.
    Why: metadata must be persisted so the app can list/serve files after restarts.
    """
    conn.execute(
        "INSERT INTO processed_files (id, path, original_name, rows, headers, uploaded_at) VALUES (?,?,?,?,?,?)",
        (pf.id, str(pf.path), pf.original_name, pf.rows, "|".join(pf.headers), pf.uploaded_at.isoformat())
    )
    conn.commit()

def db_list() -> List[ProcessedFile]:
    """
    Query all processed files (metadata) from SQLite and return them as ProcessedFile objects.
    - Ordered by uploaded_at DESC so newest uploads appear first in the UI.
    - Converts the stored headers string back into a list.
    """
    cur = conn.execute("SELECT id, path, original_name, rows, headers, uploaded_at FROM processed_files ORDER BY uploaded_at DESC")
    out = []
    for row in cur.fetchall():
        out.append(ProcessedFile(
            id=row[0],
            path=Path(row[1]),
            original_name=row[2],
            rows=row[3],
            headers=row[4].split('|') if row[4] else [],
            uploaded_at=datetime.fromisoformat(row[5])
        ))
    return out

def db_get(file_id: str) -> Optional[ProcessedFile]:
    """
    Fetch a single ProcessedFile record by ID from the DB.
    Returns None if the record doesn't exist.
    Use this to look up where the file is on disk and to display metadata.
    """
    cur = conn.execute("SELECT id, path, original_name, rows, headers, uploaded_at FROM processed_files WHERE id=?", (file_id,))
    r = cur.fetchone()
    if not r:
        return None
    return ProcessedFile(
        id=r[0],
        path=Path(r[1]),
        original_name=r[2],
        rows=r[3],
        headers=r[4].split('|') if r[4] else [],
        uploaded_at=datetime.fromisoformat(r[5])
    )

# -----------------------
# S3 upload helper
# -----------------------

def upload_to_s3(local_path: Path, key: str):
    """
    Attempt to upload the file at local_path to S3 under the given key.
    - If s3_client is not initialized or credentials are missing, log and return False.
    - Returns True on success, False otherwise.
    Why: backing up to object storage offloads long-term retention and lets you reclaim local PVC space.
    """
    if not s3_client or not has_aws_credentials():
        logger.info("Skipping S3 upload (no credentials)")
        return False
    try:
        s3_client.upload_file(str(local_path), S3_BUCKET, key, ExtraArgs={"StorageClass": "STANDARD"})
        logger.info("Uploaded %s to s3://%s/%s", local_path.name, S3_BUCKET, key)
        return True
    except (NoCredentialsError, PartialCredentialsError):
        logger.warning("AWS credentials missing, skipping upload")
    except Exception as e:
        logger.error("Failed to upload to S3: %s", e)
    return False

# -----------------------
# Routes: UI and API
# -----------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """
    Render the index page:
    - Shows a simple upload form (POST /upload)
    - Lists processed files using metadata from SQLite (id, original_name, rows, uploaded_at)
    Why it matters: the index shows metadata only (not file binaries); users click file links
    to view/download the actual CSV content.
    """
    files = [
        {
            "id": f.id,
            "original_name": f.original_name,
            "rows": f.rows,
            "uploaded_at": f.uploaded_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for f in db_list()
    ]
    return INDEX_TEMPLATE.render(files=files)

@app.post("/upload", response_class=HTMLResponse)
async def upload(file: UploadFile = File(...)):
    """
    Endpoint to receive CSV uploads.
    Steps and why each is necessary:
    1. Read uploaded bytes into memory (file.read()) — we need raw bytes to write to disk.
       - For large files, streaming would be preferable; this app assumes moderate size CSVs.
    2. Generate a UUID to avoid filename collisions and to use as the primary identifier.
    3. Write raw bytes to a file under LOCAL_STORAGE using the UUID as the filename.
       - This creates a persistent copy; when using a PVC in k8s, mount it to LOCAL_STORAGE so files persist.
    4. Decode the bytes as UTF-8 and parse CSV using csv.reader to extract the header and rows.
    5. Build a ProcessedFile with metadata (id, local path, original filename, headers, row count, timestamp).
    6. Call db_add() to persist metadata so the UI and APIs can list/manage the file later.
    7. Optionally upload the file to S3 for backup/long-term storage if credentials exist.
    8. Render an HTML preview (headers + rows) to show the uploaded content to the user.
    """
    # 1. Read the uploaded file into memory (async-safe)
    contents = await file.read()

    # 2. Use a UUID for uniqueness and to avoid filesystem safe name issues
    file_id = str(uuid.uuid4())

    # 3. Compute the local path where the file will live and write the file
    local_path = LOCAL_STORAGE / f"{file_id}.csv"
    with open(local_path, 'wb') as f:
        f.write(contents)
    # At this point, the raw CSV exists on disk at LOCAL_STORAGE/<uuid>.csv

    # 4. Parse the CSV content to retrieve header & rows for preview and metadata
    decoded = contents.decode('utf-8').splitlines()  # splitlines keeps original row structure
    reader = csv.reader(decoded)  # csv.reader handles CSV escaping, quoting, commas etc.
    rows = list(reader)
    headers = rows[0] if rows else []  # first row is header if present
    data_rows = rows[1:]  # rest are data rows

    # 5. Construct the metadata object capturing the important attributes
    processed_file = ProcessedFile(
        id=file_id,
        path=local_path,
        original_name=file.filename,
        rows=len(data_rows),
        headers=headers,
        uploaded_at=datetime.utcnow()
    )

    # 6. Persist metadata in the database so the app can recover this file after restart
    db_add(processed_file)

    # 7. Use a date-based prefix in S3 to help organize uploads by day (optional backup)
    date_prefix = datetime.utcnow().strftime('%Y/%m/%d')
    s3_key = f"uploads/{date_prefix}/{file_id}_{file.filename}"
    upload_to_s3(local_path, s3_key)

    # 8. Render the preview page showing the CSV contents in a table
    return FILE_TEMPLATE.render(file={
        'original_name': processed_file.original_name,
        'headers': processed_file.headers,
        'rows': data_rows
    })

@app.get("/file/{file_id}", response_class=HTMLResponse)
async def get_file(file_id: str):
    """
    Render the saved CSV file as an HTML table for quick inspection.
    - Looks up metadata in SQLite to find the local path.
    - Returns 404 if metadata missing, 410 if metadata exists but file is missing on disk.
    - Reason: metadata allows listing without reading the large file; path points to where
      the file is stored on disk (LOCAL_STORAGE).
    """
    pf = db_get(file_id)
    if not pf:
        return HTMLResponse("Not found", status_code=404)
    if not pf.path.exists():
        # If the DB says the file exists but the file itself was removed, return Gone (410)
        return HTMLResponse("File on disk missing", status_code=410)
    # Read and parse the CSV again to ensure we render the latest content from disk
    with open(pf.path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
        headers = rows[0] if rows else []
        data_rows = rows[1:]
    return FILE_TEMPLATE.render(file={
        'original_name': pf.original_name,
        'headers': headers,
        'rows': data_rows
    })

@app.get("/download/{file_id}")
async def download_file(file_id: str):
    """
    Download the original CSV file.
    - Uses FileResponse which sets proper headers and streams the file.
    - Raises 404 if no metadata and 410 if metadata exists but file removed.
    Why: letting users download the raw CSV preserves exact original bytes and filename.
    """
    pf = db_get(file_id)
    if not pf:
        raise HTTPException(status_code=404, detail="Not found")
    if not pf.path.exists():
        raise HTTPException(status_code=410, detail="File gone")
    return FileResponse(path=str(pf.path), filename=pf.original_name, media_type='text/csv')

@app.get("/files")
async def list_files():
    """
    JSON endpoint returning the metadata list for all processed files.
    - Useful for an API-driven frontend or automation.
    - Returns id, original_name, rows, and uploaded_at (ISO format).
    """
    return [
        {
            "id": f.id,
            "original_name": f.original_name,
            "rows": f.rows,
            "uploaded_at": f.uploaded_at.isoformat()
        } for f in db_list()
    ]

@app.get("/healthz")
async def health():
    """
    Simple liveness/readiness endpoint used by k8s probes.
    - Returns {"status": "ok"} which indicates the application process is running.
    - In a more advanced setup you might check DB connectivity, disk space, or S3 access here.
    """
    return {"status": "ok"}

# -----------------------
# Entrypoint for local run
# -----------------------

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    # Running directly via `python main.py` launches the server on the configured PORT.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
# Run with: uvicorn main:app --reload --host 0.0.0.0 --port 8000
