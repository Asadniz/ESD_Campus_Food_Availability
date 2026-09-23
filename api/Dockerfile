FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY campus_api ./campus_api
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "campus_api.main"]
