"""Main FastAPI application for the CSV (SOH) processor.

Features:
* Upload CSV and parse headers/rows
* Persist metadata in SQLite (optionally backed by PVC in K8s)
* List processed files (HTML + JSON endpoints)
* View / download an individual file
* Optional S3 upload (skips gracefully if credentials absent)
* Health endpoint for readiness / liveness probes
* Static assets served by Nginx in Kubernetes via a shared volume; also mounted here for local dev.
"""

import csv
import os
import uuid
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from jinja2 import Template

S3_BUCKET = os.getenv("S3_BUCKET", "soh-files-bucket")
S3_REGION = os.getenv("AWS_REGION", "us-east-1")
LOCAL_STORAGE = Path(os.getenv("LOCAL_STORAGE", "./data"))
LOCAL_STORAGE.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("soh-app")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='%(asctime)s %(levelname)s %(message)s')

def has_aws_credentials() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))

try:
    s3_client = boto3.client("s3", region_name=S3_REGION)
except Exception as e:
    logger.warning("Failed to create S3 client: %s", e)
    s3_client = None

app = FastAPI(title="SOH CSV Processor")
# Mount static for local development convenience (in cluster, Nginx serves them)
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

INDEX_TEMPLATE = Template("""
<!doctype html>
<html><head><title>SOH Processor</title><link rel=\"stylesheet\" href=\"/static/style.css\" /></head>
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

class ProcessedFile(BaseModel):
    id: str
    path: Path
    original_name: str
    rows: int
    headers: List[str]
    uploaded_at: datetime

processed_index: List[ProcessedFile] = []

# SQLite persistence
DB_PATH = os.getenv("DB_PATH", "processed_files.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("""CREATE TABLE IF NOT EXISTS processed_files (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    rows INTEGER NOT NULL,
    headers TEXT,
    uploaded_at TEXT NOT NULL
)""")
conn.commit()

def db_add(pf: ProcessedFile):
    conn.execute(
        "INSERT INTO processed_files (id, path, original_name, rows, headers, uploaded_at) VALUES (?,?,?,?,?,?)",
        (pf.id, str(pf.path), pf.original_name, pf.rows, "|".join(pf.headers), pf.uploaded_at.isoformat())
    )
    conn.commit()

def db_list() -> List[ProcessedFile]:
    cur = conn.execute("SELECT id, path, original_name, rows, headers, uploaded_at FROM processed_files ORDER BY uploaded_at DESC")
    out = []
    for row in cur.fetchall():
        out.append(ProcessedFile(
            id=row[0], path=Path(row[1]), original_name=row[2], rows=row[3], headers=row[4].split('|') if row[4] else [], uploaded_at=datetime.fromisoformat(row[5])
        ))
    return out

def db_get(file_id: str) -> Optional[ProcessedFile]:
    cur = conn.execute("SELECT id, path, original_name, rows, headers, uploaded_at FROM processed_files WHERE id=?", (file_id,))
    r = cur.fetchone()
    if not r:
        return None
    return ProcessedFile(id=r[0], path=Path(r[1]), original_name=r[2], rows=r[3], headers=r[4].split('|') if r[4] else [], uploaded_at=datetime.fromisoformat(r[5]))

def upload_to_s3(local_path: Path, key: str):
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

@app.get("/", response_class=HTMLResponse)
async def index():
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
    contents = await file.read()
    file_id = str(uuid.uuid4())
    local_path = LOCAL_STORAGE / f"{file_id}.csv"
    with open(local_path, 'wb') as f:
        f.write(contents)

    decoded = contents.decode('utf-8').splitlines()
    reader = csv.reader(decoded)
    rows = list(reader)
    headers = rows[0] if rows else []
    data_rows = rows[1:]

    processed_file = ProcessedFile(
        id=file_id,
        path=local_path,
        original_name=file.filename,
        rows=len(data_rows),
        headers=headers,
        uploaded_at=datetime.utcnow()
    )
    db_add(processed_file)

    # Upload to S3 (key with date prefix)
    date_prefix = datetime.utcnow().strftime('%Y/%m/%d')
    s3_key = f"uploads/{date_prefix}/{file_id}_{file.filename}"
    upload_to_s3(local_path, s3_key)

    return FILE_TEMPLATE.render(file={
        'original_name': processed_file.original_name,
        'headers': processed_file.headers,
        'rows': data_rows
    })

@app.get("/file/{file_id}", response_class=HTMLResponse)
async def get_file(file_id: str):
    pf = db_get(file_id)
    if not pf:
        return HTMLResponse("Not found", status_code=404)
    if not pf.path.exists():
        return HTMLResponse("File on disk missing", status_code=410)
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
    pf = db_get(file_id)
    if not pf:
        raise HTTPException(status_code=404, detail="Not found")
    if not pf.path.exists():
        raise HTTPException(status_code=410, detail="File gone")
    return FileResponse(path=str(pf.path), filename=pf.original_name, media_type='text/csv')

@app.get("/files")
async def list_files():
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
    return {"status": "ok"}

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

# Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
