FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Add src to PYTHONPATH so that imports work correctly
ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# Run the web application automatically
CMD ["python", "src/web.py"]
