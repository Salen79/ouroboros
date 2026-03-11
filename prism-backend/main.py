# main.py
from fastapi import FastAPI
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Security middleware will be added here
# Logging config will be here

# Schemas will be imported from schemas.py
# Config will be loaded from config.py

# TODO: Add more endpoints for Prism functionality
