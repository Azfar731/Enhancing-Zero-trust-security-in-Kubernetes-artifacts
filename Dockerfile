# Dockerfile for creating Custom Controller image

# Python3 base image
FROM python:3.9-slim-buster
# Set working directory in the container
WORKDIR /app
# Copy the requirements file into the container
COPY requirements.txt .
# Install needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Copy the script into the container
COPY deny_automation.py .
# Command to run the script when the container starts
# The script will read NAMESPACE_TO_WATCH from an environment variable
CMD ["python", "deny_automation.py"]