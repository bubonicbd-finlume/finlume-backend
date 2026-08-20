"""
app.py
================================================================
FastAPI backend wiring bank_parsers.py + categorizer.py +
active_learning.py for the Finlume web app.

Endpoints:
  POST /parse/pdf           Parse a bank statement PDF
  POST /parse/csv           Parse a bank statement CSV
  POST /categorize/one      Categorize a single transaction
  POST /correct             Store a user correction (active learning)
  GET  /accuracy/{bank}     Per-bank accuracy stats
  GET  /monthly-report      Monthly active learning report

Database: per-user SQLite in /tmp/ledgerly/{user_id}/corrections.db
          (or swap _connect() in active_learning.py to use Supabase/Postgres)

Security: expects an Authorization header with a JWT; extracts user_id from claims.
================================================================
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import tempfile
import json
from pathlib import Path
import jwt
from functools import lru_cache

# Import the validated pipeline
from pipeline import (
    process_statement, process_statement_csv, apply_user_correction, categorize_one
)
from active_learning import (
    monthly_retraining, track_per_bank_accuracy, analyze_errors
)

app = FastAPI(title="Ledgerly Bank Statement API", version="1.0.0")

# CORS for the web app (adjust origin as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://ledgerly.example.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------
# Config
# ---------------------------------------------------------------

DB_ROOT = Path(tempfile.gettempdir()) / "ledgerly"
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"

def get_user_id(authorization: str = Header(...)) -> str:
    """Extract and verify JWT, return user_id."""
    try:
        # Expect "Bearer <token>"
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid auth scheme")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing 'sub' claim")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

def get_user_db_path(user_id: str) -> str:
    """Return the per-user SQLite database path."""
    user_dir = DB_ROOT / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return str(user_dir / "corrections.db")

# ---------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------

@app.post("/parse/pdf")
async def parse_pdf(
    file: UploadFile = File(...),
    bank: str = Form(...),
    user_id: str = Depends(get_user_id),
):
    """
    Parse a bank statement PDF.
    
    Args:
        file: PDF file (multipart/form-data)
        bank: Bank name (SBI, HDFC, ICICI, AXIS, INDUSIND, YES, UNION, MAHARASHTRA)
        user_id: From JWT (auto-extracted)
    
    Returns:
        {
            "bank": "SBI",
            "source_format": "pdf",
            "total_transactions": 363,
            "auto_categorized": 352,
            "needs_review": 11,
            "auto_categorization_rate": 0.97,
            "validation_issues": [...],
            "transactions": [
                {
                    "transaction_id": "uuid5-stable-id",
                    "date": "2024-01-15",
                    "narration_raw": "UPI/DR/123456/JOHN/HDFC/...",
                    "amount": 1500.00,
                    "transaction_type": "debit",
                    "balance": 45000.00,
                    "predicted_category": "Dining",
                    "confidence": 0.95,
                    "user_action_required": false,
                    "merchant_name": "John",
                    "merchant_source": "UPI",
                    ...
                },
                ...
            ]
        }
    """
    try:
        # Save to temp file for pdf processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        db_path = get_user_db_path(user_id)
        result = process_statement(tmp_path, bank, db_path=db_path)
        
        # Cleanup
        os.unlink(tmp_path)
        
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/parse/csv")
async def parse_csv(
    file: UploadFile = File(...),
    bank: str = Form(...),
    user_id: str = Depends(get_user_id),
):
    """
    Parse a bank statement CSV (preferred over PDF).
    
    Returns same shape as /parse/pdf, plus a bank_summary_cross_check field:
        "bank_summary_cross_check": {
            "summary_available": true,
            "debit_count": [281, 281, true],
            "credit_count": [82, 82, true],
            "total_debits": [3374557.79, 3374557.79, true],
            "total_credits": [3396839.40, 3396839.40, true]
        }
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        db_path = get_user_db_path(user_id)
        result = process_statement_csv(tmp_path, bank, db_path=db_path)
        
        os.unlink(tmp_path)
        
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/categorize/one")
async def categorize_transaction(
    narration: str = Form(...),
    amount: float = Form(None),
    date: str = Form(None),
    is_credit: bool = Form(False),
    user_id: str = Depends(get_user_id),
):
    """
    Categorize a single transaction narration (e.g. re-categorize after
    editing, or categorize an entry typed by hand).
    
    Returns: Same shape as a transaction object in /parse/pdf result.
    """
    try:
        db_path = get_user_db_path(user_id)
        result = categorize_one(
            narration,
            amount=amount,
            date_str=date,
            is_credit=is_credit,
            db_path=db_path,
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/correct")
async def store_correction(
    transaction_id: str = Form(...),
    corrected_category: str = Form(...),
    bank: str = Form(...),
    narration: str = Form(...),
    amount: float = Form(None),
    merchant_name: str = Form(None),
    predicted_category: str = Form(None),
    confidence: float = Form(None),
    user_notes: str = Form(None),
    user_id: str = Depends(get_user_id),
):
    """
    Store a user correction (active learning). Once called, every future
    transaction matching this merchant/narration automatically uses the
    corrected category. Works retroactively on the current statement too
    (with recategorize_existing on the frontend).
    
    Returns: { "status": "stored", "rule_applied_to": N_future_transactions, ... }
    """
    try:
        db_path = get_user_db_path(user_id)
        result = apply_user_correction(
            transaction={
                "transaction_id": transaction_id,
                "date": None,  # optional; not always in hand
                "narration_raw": narration,
                "amount": amount,
                "merchant_name": merchant_name,
                "predicted_category": predicted_category,
                "confidence": confidence,
            },
            corrected_category=corrected_category,
            bank=bank,
            db_path=db_path,
            user_notes=user_notes,
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/accuracy/{bank}")
async def accuracy_by_bank(
    bank: str,
    user_id: str = Depends(get_user_id),
):
    """
    Per-bank categorization accuracy over the last 30 days.
    
    Returns:
        {
            "run_timestamp": "2024-02-15T10:30:00Z",
            "overall_accuracy": 0.97,
            "per_bank": {
                "SBI": {
                    "accuracy": 0.97,
                    "total": 363,
                    "correct": 352,
                    "trend": 0.02  # vs previous 30 days
                },
                ...
            }
        }
    """
    try:
        db_path = get_user_db_path(user_id)
        report = track_per_bank_accuracy(db_path=db_path)
        
        if bank.upper() not in report.get("per_bank", {}):
            raise HTTPException(status_code=404, detail=f"No data for bank: {bank}")
        
        return JSONResponse(report)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/monthly-report")
async def monthly_report(
    user_id: str = Depends(get_user_id),
):
    """
    Full monthly active-learning report: accuracy, top misclassifications,
    suggested Tier 1 rule additions, weak banks.
    
    Returns:
        {
            "run_timestamp": "2024-02-15T10:30:00Z",
            "accuracy_report": {...},
            "error_report": {...},
            "tier1_rule_suggestions": [
                {
                    "suggested_category": "Groceries",
                    "based_on_bank": "SBI",
                    "frequency": 3,
                    "note": "Seen 3x this period — consider adding a keyword rule."
                },
                ...
            ],
            "weak_banks": ["ICICI"],
            "tier2_ml_retrain_status": "not_yet_implemented — Tier 2 remains..."
        }
    """
    try:
        db_path = get_user_db_path(user_id)
        report = monthly_retraining(db_path=db_path)
        return JSONResponse(report)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------------------------------------------------------------
# Health check
# ---------------------------------------------------------------

@app.get("/health")
async def health():
    """Readiness probe for deployment."""
    return {"status": "ok", "service": "ledgerly-bank-statement-api"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
