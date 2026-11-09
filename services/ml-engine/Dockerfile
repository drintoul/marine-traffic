FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn redis scikit-learn numpy pydantic websockets
COPY server.py .
COPY train.py .
COPY static ./static
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
