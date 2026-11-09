FROM python:3.11-slim
WORKDIR /app
RUN pip install redis requests pydantic
COPY worker.py .
CMD ["python", "worker.py"]
