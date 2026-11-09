FROM python:3.11-slim
WORKDIR /app
RUN pip install redis websockets
COPY main.py .
CMD ["python", "main.py"]
