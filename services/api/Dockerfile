FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.4 "uvicorn==0.32.0" "psycopg[binary]==3.2.3" redis==5.2.0
COPY main.py catalog.py lab.py ./
COPY static ./static
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
