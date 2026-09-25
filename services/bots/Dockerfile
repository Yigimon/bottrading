FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3" redis==5.2.0
COPY main.py .
CMD ["python", "-u", "main.py"]
