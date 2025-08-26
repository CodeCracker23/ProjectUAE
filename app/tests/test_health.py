from fastapi.testclient import TestClient
try:
    from app.main import app
except ModuleNotFoundError:
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    from main import app  # type: ignore

client = TestClient(app)

def test_health():
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'

def test_upload_csv():
    csv_content = 'col1,col2\nval1,val2\n'
    files = {'file': ('test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
    r = client.post('/upload', files=files)
    assert r.status_code == 200
    assert 'test.csv' in r.text
    # fetch json list
    r2 = client.get('/files')
    assert r2.status_code == 200
    data = r2.json()
    assert len(data) >= 1
    file_id = data[0]['id']
    # download
    r3 = client.get(f'/download/{file_id}')
    assert r3.status_code == 200
    assert r3.headers['content-type'].startswith('text/csv')
