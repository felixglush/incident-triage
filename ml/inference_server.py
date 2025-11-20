"""ML Inference Service - Stub for development"""
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ML Inference Service")


class ClassificationRequest(BaseModel):
    text: str


class ClassificationResponse(BaseModel):
    severity: str
    confidence: float


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/classify", response_model=ClassificationResponse)
async def classify(request: ClassificationRequest):
    """Classify alert severity - stub implementation"""
    return {
        "severity": "medium",
        "confidence": 0.7
    }


@app.post("/extract-entities")
async def extract_entities(request: ClassificationRequest):
    """Extract entities from text - stub implementation"""
    return {
        "entities": []
    }
