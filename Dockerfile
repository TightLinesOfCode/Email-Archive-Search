FROM python:3.12-slim

WORKDIR /app

# Install dependencies when requirements.txt exists
COPY requirements.txt* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

COPY . .

# /pop-email-archive is the mount point for local file access
VOLUME ["/pop-email-archive"]

# Allow modules inside src/ to import each other without a package prefix
ENV PYTHONPATH=/app/src

# Default port — overridden at runtime via PORT in .env
ENV PORT=5000
EXPOSE ${PORT}

CMD ["python", "main.py"]
