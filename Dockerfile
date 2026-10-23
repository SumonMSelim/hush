FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY hush ./hush
COPY fixtures ./fixtures
RUN pip install --no-cache-dir .
CMD ["python", "-m", "hush.server"]
