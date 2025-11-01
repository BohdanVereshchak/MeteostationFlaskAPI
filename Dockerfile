# Use Python base image
FROM python:3.11-slim

WORKDIR /app

# Copy your files
COPY . .

# Install dependencies
RUN pip install -r requirements.txt

# Expose port 8080 (Cloud Run default)
EXPOSE 8080

# Start your Flask app
CMD ["python", "app.py"]
