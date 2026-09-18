FROM python:3.12-slim
WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/worker.py .
COPY worker/etl ./etl
COPY shared/s3util.py ./s3util.py
COPY infra/init.sql ./infra/init.sql
CMD ["python", "worker.py"]
