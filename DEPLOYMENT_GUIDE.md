# Finlume Finance + Python Backend — Complete Deployment Guide

## Overview

You now have:

1. **Frontend** (`finlume_backend_integrated.html`) — Single-file React app that can use either:
   - **Client-side parsing** (works offline, no backend needed)
   - **Backend parsing** (97% accuracy on real data, persistent corrections)

2. **Backend** (`app.py`) — FastAPI service wrapping your validated Python pipeline:
   - `bank_parsers.py` (bank-specific extraction)
   - `categorizer.py` (rule-based + learned categorization)
   - `active_learning.py` (persistent corrections)

3. **Database** — Per-user SQLite (local) or Supabase/Postgres (production)

---

## Quick Start (5 mins)

### 1. Deploy Backend to Render (Free Tier)

```bash
# Push code to GitHub
git init
git add app.py requirements.txt
git commit -m "Ledgerly backend"
git push origin main

# Go to https://render.com
# New → Web Service
# Connect GitHub repo
# Environment:
#   Runtime: Python 3.11
#   Build command: pip install -r requirements.txt
#   Start command: uvicorn app:app --host 0.0.0.0 --port 8000
#   Add env var: JWT_SECRET=your-secret-here (generate one)
# Deploy
```

Once deployed, you'll have a URL like `https://ledgerly-backend-abc123.onrender.com`.

### 2. Configure Frontend

Open `finlume_backend_integrated.html` in a text editor:

```javascript
const BACKEND_CONFIG = {
  apiUrl: "https://ledgerly-backend-abc123.onrender.com",  // ← Update this
  enabled: true,  // ← Set to true
};
```

### 3. Generate JWT for Testing

```python
import jwt
from datetime import datetime, timedelta

JWT_SECRET = "your-secret-here"  # Must match backend's JWT_SECRET
user_id = "test@example.com"
token = jwt.encode(
    {"sub": user_id, "exp": datetime.utcnow() + timedelta(hours=24)},
    JWT_SECRET,
    algorithm="HS256"
)
print(token)
```

### 4. Open App & Configure JWT

1. Open `finlume_backend_integrated.html` in browser
2. Go to Settings → Bank Statement Parser (Backend)
3. Paste the JWT token
4. Click "Save"

### 5. Test Upload

- Upload a bank statement PDF or CSV
- Should show "Backend parser enabled (97% accuracy on real data)"
- Backend will parse it in seconds

---

## Production Deployment

### Option A: Heroku (Easiest, $7/month)

```bash
# Install Heroku CLI
brew install heroku

# Log in
heroku login

# Create app
heroku create ledgerly-backend

# Set environment
heroku config:set JWT_SECRET=$(openssl rand -hex 32) -a ledgerly-backend

# Deploy
git push heroku main

# Check logs
heroku logs -a ledgerly-backend -t
```

Your backend is live at `https://ledgerly-backend.herokuapp.com`.

### Option B: Railway (Free $5/month credit)

1. Go to https://railway.app
2. New Project → GitHub → Select repo
3. Auto-detect Python
4. Add env var: `JWT_SECRET=<generated-secret>`
5. Deploy

### Option C: AWS Lambda + API Gateway (Serverless)

```bash
pip install mangum

# lambda_handler.py
from mangum import Mangum
from app import app

handler = Mangum(app)
```

Then deploy using AWS SAM or Serverless Framework.

### Option D: Docker (Your own server)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t ledgerly-backend .
docker run -e JWT_SECRET=your-secret -p 8000:8000 ledgerly-backend
```

---

## Database Setup (Production)

### SQLite (Default, Local)

- Per-user database at `/tmp/ledgerly/{user_id}/corrections.db`
- Works out-of-box
- Data lost if container restarts (for production, use option below)

### Supabase/Postgres (Recommended)

1. Create Supabase account (free tier: 500MB storage)
2. Create new project
3. Update `active_learning.py`:

```python
# At the top
import os
import psycopg2

def _connect(db_path=None):
    """Use Postgres instead of SQLite"""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.row_factory = lambda cursor, row: dict(
        zip([c[0] for c in cursor.description], row)
    )
    return conn

def init_db(db_path=None):
    """Create tables if they don't exist"""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            transaction_id TEXT PRIMARY KEY,
            date TEXT,
            bank TEXT,
            narration TEXT,
            amount REAL,
            merchant_extracted TEXT,
            predicted_category TEXT,
            predicted_confidence REAL,
            corrected_category TEXT,
            user_notes TEXT,
            correction_timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counterparty_rules (
            counterparty_key TEXT PRIMARY KEY,
            category TEXT,
            times_confirmed INTEGER,
            last_confirmed TEXT
        )
    """)
    conn.commit()
    conn.close()
```

4. Set env var in production:
   ```
   DATABASE_URL=postgresql://user:pass@db.supabase.co:5432/postgres
   ```

---

## Frontend Configuration

### Option 1: Host on Netlify (Recommended)

```bash
# Create netlify.toml in project root
[build]
  publish = "."
  command = "echo 'Static site'"

[context.production.environment]
  VITE_BACKEND_URL = "https://ledgerly-backend.onrender.com"

[[headers]]
  for = "finlume_backend_integrated.html"
  [headers.values]
    Cache-Control = "public, max-age=3600"
```

Drop `finlume_backend_integrated.html` into Netlify → Auto-deploys.

### Option 2: Host on GitHub Pages

```bash
# Create docs/ folder
mkdir docs
cp finlume_backend_integrated.html docs/index.html

# Push to GitHub
git add docs/
git commit -m "Deploy frontend"
git push

# Go to repo Settings → Pages → Deploy from branch → docs/ folder
# Your app is now at https://{username}.github.io/{repo}
```

### Option 3: Self-hosted

Just serve the HTML file with any web server:

```bash
python -m http.server 8080
# Open http://localhost:8080/finlume_backend_integrated.html
```

Or with nginx:

```nginx
server {
    listen 80;
    server_name example.com;
    
    root /var/www/finlume;
    index finlume_backend_integrated.html;
    
    location / {
        try_files $uri $uri/ /finlume_backend_integrated.html;
    }
}
```

---

## Authentication Integration

The backend expects JWTs with a `sub` claim. Integrate with your auth provider:

### Supabase Auth

```javascript
// In the HTML, after Supabase sign-in:
const session = await supabaseClient.auth.getSession();
if (session?.session?.access_token) {
  setBackendJwt(session.session.access_token, false);
}
```

### Auth0

```javascript
import { useAuth0 } from "@auth0/auth0-react";

const { getAccessTokenSilently } = useAuth0();

async function getBackendJwt() {
  const token = await getAccessTokenSilently({
    audience: "https://your-api-identifier",
  });
  return token;
}
```

### Firebase

```javascript
const currentUser = firebase.auth().currentUser;
const token = await currentUser.getIdToken();
setBackendJwt(token, false);
```

---

## API Endpoints Reference

All endpoints require `Authorization: Bearer <JWT>` header.

### POST /parse/pdf

Parse a PDF statement.

```bash
curl -X POST https://ledgerly-backend.onrender.com/parse/pdf \
  -H "Authorization: Bearer YOUR_JWT" \
  -F "file=@statement.pdf" \
  -F "bank=SBI"
```

**Response:**
```json
{
  "bank": "SBI",
  "source_format": "pdf",
  "total_transactions": 363,
  "auto_categorized": 352,
  "needs_review": 11,
  "auto_categorization_rate": 0.97,
  "transactions": [
    {
      "transaction_id": "stable-uuid",
      "date": "2024-01-15",
      "amount": 1500.00,
      "transaction_type": "debit",
      "predicted_category": "Dining",
      "confidence": 0.95,
      "merchant_name": "Swiggy",
      "user_action_required": false
    }
  ]
}
```

### POST /parse/csv

Parse a CSV statement (preferred for accuracy).

```bash
curl -X POST https://ledgerly-backend.onrender.com/parse/csv \
  -H "Authorization: Bearer YOUR_JWT" \
  -F "file=@statement.csv" \
  -F "bank=SBI"
```

**Additional response field:**
```json
{
  "bank_summary_cross_check": {
    "summary_available": true,
    "debit_count": [281, 281, true],
    "credit_count": [82, 82, true],
    "total_debits": [3374557.79, 3374557.79, true],
    "total_credits": [3396839.40, 3396839.40, true]
  }
}
```

### POST /correct

Store a user correction (active learning).

```bash
curl -X POST https://ledgerly-backend.onrender.com/correct \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "transaction_id=stable-uuid&corrected_category=Dining&bank=SBI&narration=SWIGGY&amount=1500&merchant_name=Swiggy"
```

**Response:**
```json
{
  "status": "stored",
  "transaction_id": "stable-uuid",
  "corrected_category": "Dining",
  "note": "Every future Swiggy transaction will auto-categorize as Dining."
}
```

### GET /accuracy/{bank}

Get accuracy stats for a specific bank.

```bash
curl https://ledgerly-backend.onrender.com/accuracy/SBI \
  -H "Authorization: Bearer YOUR_JWT"
```

### GET /monthly-report

Get active learning report (suggested rules, weak banks, etc.).

```bash
curl https://ledgerly-backend.onrender.com/monthly-report \
  -H "Authorization: Bearer YOUR_JWT"
```

---

## Troubleshooting

### "Backend auth token not found"

- Go to Settings → Bank Statement Parser (Backend)
- Paste your JWT token
- Click "Save"

### "API error 401: Invalid token"

- JWT expired or invalid
- Regenerate a new JWT using the script above
- Make sure `JWT_SECRET` in backend matches the secret used to generate the token

### "Could not read that PDF: ..."

- PDF might be corrupted or in an unsupported format
- Try exporting as a different format from your bank
- Or use the CSV export (backend will handle it with the footer cross-check)

### "Backend parsing failed, falling back to client-side"

- Backend might be down or unreachable
- Check `BACKEND_CONFIG.apiUrl` in the HTML
- Check backend logs: `heroku logs -a ledgerly-backend -t`
- App will automatically fall back to client-side parsing (less accurate, but works)

### Tests Failing

```bash
# Run the Python test suite
python test_accuracy.py

# Should show:
# SBI: 97.0% (352/363)
# Multi-bank: 87.9% (771/871)
```

If tests fail, check:
- `pdfplumber` version (should be 0.10.4+)
- PDF files are readable (`pdfplumber /path/to/pdf.pdf`)
- Sample statements are in the right format

---

## Support & Next Steps

### For issues with parsing:
1. Enable browser DevTools → Network tab
2. Capture the API request/response
3. Check backend logs
4. File an issue with the PDF or CSV sample

### To add more banks:
1. Get a real statement PDF/CSV from the bank
2. Run it through `bank_parsers.py` locally
3. Implement bank-specific parser (e.g., `parse_hdfc_pdf()`)
4. Test against the README's validation criteria (exact match on footer totals)
5. Add to `PARSERS` dict in `bank_parsers.py`

### To improve categorization:
1. Upload statements via the app
2. Correct a few categories
3. Check `/monthly-report` endpoint for suggested new rules
4. Add high-confidence keywords to `categorizer.py`

---

## File Summary

```
ledgerly-backend-repo/
├── app.py                              # FastAPI backend (NEW)
├── requirements.txt                    # Python deps (NEW)
├── bank_parsers.py                     # Bank-specific parsing
├── categorizer.py                      # Categorization rules
├── narration_processor.py               # Narration cleaning
├── active_learning.py                  # Persistent corrections
├── pipeline.py                         # Integration layer
├── validation_layer.py                 # Duplicate/balance checks
├── test_accuracy.py                    # Test suite
├── finlume_backend_integrated.html      # Frontend (NEW)
├── BACKEND_INTEGRATION.md               # Backend setup
├── DEPLOYMENT_GUIDE.md                  # This file
└── README.md                            # Original project docs
```

---

## Performance Notes

- **PDF parsing**: 10-60 seconds (depends on page count, backend hardware)
- **CSV parsing**: <1 second (no OCR involved)
- **Categorization**: 10-100ms per transaction
- **Active learning**: Corrections apply instantly to future transactions

For high-volume use (1000+ transactions/month), consider:
- Batch imports (combine multiple statements)
- Async processing (queue task, notify when ready)
- Caching (memoize categorization results for identical narrations)

---

## Security Checklist

- [ ] Set a strong `JWT_SECRET` (min 32 chars)
- [ ] Use HTTPS in production (Render, Railway, Heroku all provide free SSL)
- [ ] Keep dependencies updated: `pip install --upgrade -r requirements.txt`
- [ ] Rotate JWT secrets quarterly
- [ ] Use Supabase/Postgres in production (not /tmp SQLite)
- [ ] Enable CORS only for your frontend domain
- [ ] Monitor backend logs for errors/abuse
- [ ] Rate-limit API endpoints if needed

---

## Questions?

Refer to:
- `BACKEND_INTEGRATION.md` — API details
- `README.md` — Original project notes
- `app.py` — Endpoint documentation (docstrings)
- Test data in `test_accuracy.py` for example inputs/outputs
