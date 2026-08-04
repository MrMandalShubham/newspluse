# NewsPulse app image — Python 3.12 slim.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Tests are copied so the image can run the gate in CI/DO if needed.
COPY tests ./tests

EXPOSE 8000

CMD ["uvicorn", "newspulse.main:app", "--host", "0.0.0.0", "--port", "8000"]
