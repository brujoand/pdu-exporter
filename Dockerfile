FROM python:3.12-slim

RUN pip install --no-cache-dir prometheus-client httpx

COPY exporter.py /exporter.py

CMD ["python", "/exporter.py"]
