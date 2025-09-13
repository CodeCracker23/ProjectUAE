FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Without writebytecode, Python generates __pycache__/*.pyc files whenever code runs
# pybuffered=1 ogs are flushed directly to the terminal (real-time) makes debugging easier 

