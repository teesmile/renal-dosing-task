FROM python:3.12-slim-bookworm

WORKDIR /app
COPY patients.csv labs.csv meds.csv rules.json /app/
RUN mkdir -p /app/output
