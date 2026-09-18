FROM python:3.12-slim
WORKDIR /app
COPY scaler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scaler/scaler.py .
CMD ["python", "scaler.py"]
