# The monitor with the tools it calls: pdftotext, OCRmyPDF with Tesseract's Spanish model, and 7-Zip with RAR.
FROM python:3.12-slim-trixie

# 7zip-rar is in Debian's non-free component
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils tesseract-ocr tesseract-ocr-spa ghostscript 7zip 7zip-rar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src src
COPY db db
RUN pip install --no-cache-dir -e . "ocrmypdf==17.13.0"

ENTRYPOINT ["python", "-u", "-m", "seace_monitor"]
