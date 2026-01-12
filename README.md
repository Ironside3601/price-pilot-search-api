# Search API

FastAPI service for multi-retailer product search on Google Custom Search.

## Quick Start

### 1. Prerequisites
- GitHub repository connected to this folder
- Google Cloud project: `price-pilot-1765213055260`
- Service account: `search-api-sa@price-pilot-1765213055260.iam.gserviceaccount.com`

### 2. GitHub Setup (One-time)

1. **Add GCP Service Account Key as GitHub Secret**
   - Go to: `https://github.com/Ironside3601/price-pilot-search-api/settings/secrets/actions`
   - Click **New repository secret**
   - Name: `GCP_SA_KEY`
   - Value: Base64-encoded service account JSON key
     ```bash
     base64 -w 0 /path/to/service-account.json
     ```

2. **Verify workflow file exists**
   ```bash
   .github/workflows/deploy.yml
   ```

### 3. Deploy (Branch Workflow)

```bash
# Create feature branch
git checkout -b feature/your-changes

# Make changes and commit
git add .
git commit -m "Your changes"

# Push branch
git push origin feature/your-changes

# On GitHub: Create Pull Request → Merge to main
```

When you merge to `main`, GitHub Actions will:
1. Run unit tests
2. Build Docker image
3. Push to Container Registry
4. Deploy to Cloud Run

## How It Works

```
You: Push feature branch → Create PR → Merge to main
    ↓
GitHub Actions triggered (on merge to main)
    ↓
Tests run (pytest)
    ↓
If tests pass → Build Docker image
    ↓
Push to Google Container Registry
    ↓
Deploy to Cloud Run
    ↓
Service is live
```

## Endpoints

- `GET /health` - Health check
- `GET /retailers` - List retailers
- `POST /search` - Search across retailers
  ```json
  {
    "searchQuery": "laptop",
    "productTitle": "Dell XPS 13"
  }
  ```

## Testing Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Start server
python -m uvicorn search_api:app --reload --port 5001
```

## File Structure

```
search_api/
├── search_api.py           # Main API code
├── .github/workflows/      # GitHub Actions
│   └── deploy.yml          # Deployment pipeline
├── tests/
│   ├── __init__.py
│   └── test_search_api.py  # Unit tests
├── Dockerfile              # Docker configuration
├── .gitignore              # Git exclusions
├── .dockerignore            # Docker build exclusions
└── requirements.txt        # Python dependencies
```

## Troubleshooting

**Deployment failed?**
- Check GitHub Actions tab: `Actions` → Latest run → View logs
- View Cloud Run logs: `gcloud run services logs read search-api --region europe-west1`

**Tests failing?**
- Run locally: `pytest tests/ -v`
- Check requirements installed: `pip install -r requirements.txt`

**Need to rollback?**
- Create branch: `git checkout -b fix/rollback`
- Revert commit: `git revert HEAD`
- Push branch: `git push origin fix/rollback`
- Create PR on GitHub → Merge to main
- Automatic redeploy with previous version

## Environment Variables

Cloud Run automatically sets:
- `PORT=8080` (listen port)
- Google Cloud credentials (via Workload Identity)

## Secrets Management

API keys stored in Google Secret Manager:
- `GOOGLE_API_KEY` - Google Custom Search API
- `GOOGLE_CX` - Custom search engine ID
- `OPENROUTER_API_KEY` - LLM API key

Accessed at runtime via `get_secret()` function in code.
