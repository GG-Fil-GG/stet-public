# Deploying to Streamlit Cloud

This guide covers deploying the Comment Addresser app to Streamlit Cloud for public/shared access.

---

## Prerequisites

- [x] GitHub repository (already done: `GG-Fil-GG/comments_addresser`)
- [x] `requirements.txt` with all dependencies (already exists)
- [ ] Streamlit Cloud account (free)

---

## Step 1: Create Streamlit Cloud Account

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click "Sign up" → Sign in with GitHub
3. Authorize Streamlit to access your repositories

---

## Step 2: Prepare the Repository

### 2.1 Verify `requirements.txt`

Ensure all dependencies are listed. Current contents should include:
```
python-docx
openai
python-dotenv
streamlit
requests
```

### 2.2 Create `.streamlit/config.toml` (Optional)

For custom theming or settings:

```bash
mkdir -p .streamlit
```

Create `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#4CAF50"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"

[server]
maxUploadSize = 50
```

### 2.3 Handle Secrets (API Keys)

**Important:** Never commit API keys to GitHub.

Streamlit Cloud has built-in secrets management. Create `.streamlit/secrets.toml` locally (add to `.gitignore`):
```toml
OPENAI_API_KEY = "sk-your-key-here"
```

You'll add these secrets via the Streamlit Cloud dashboard after deployment.

---

## Step 3: Deploy

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **"New app"**
3. Fill in:
   - **Repository:** `GG-Fil-GG/comments_addresser`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **"Deploy!"**

Deployment takes 2-5 minutes. You'll get a URL like:
```
https://gg-fil-gg-comments-addresser-app-xxxxx.streamlit.app
```

---

## Step 4: Configure Secrets

After deployment:

1. Click the **⋮** menu on your app dashboard
2. Select **"Settings"** → **"Secrets"**
3. Add your secrets in TOML format:
   ```toml
   OPENAI_API_KEY = "sk-your-actual-key"
   ```
4. Click **"Save"** — app will restart automatically

---

## Step 5: Update the App to Use Streamlit Secrets

Modify how the app reads the API key. In `src/llm_handler.py`, update the initialization:

```python
# Current (local .env)
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# Updated (works both locally and on Streamlit Cloud)
import streamlit as st

def get_api_key():
    # Try Streamlit secrets first (for cloud deployment)
    try:
        return st.secrets["OPENAI_API_KEY"]
    except:
        # Fall back to environment variable (for local development)
        from dotenv import load_dotenv
        load_dotenv()
        return os.getenv("OPENAI_API_KEY")
```

---

## Step 6: Test the Deployment

1. Visit your app URL
2. Upload a test `.docx` file
3. Verify:
   - [ ] File upload works
   - [ ] Comments are extracted
   - [ ] LLM generation works (if API key configured)
   - [ ] Export produces a valid `.docx`

---

## Ongoing: Auto-Deploy on Push

Streamlit Cloud automatically redeploys when you push to `main`:

```bash
git add .
git commit -m "Update feature"
git push origin main
# → Streamlit Cloud detects push and redeploys (~1-2 min)
```

---

## Limitations of Streamlit Cloud (Free Tier)

| Limitation | Impact |
|------------|--------|
| 1 GB memory | Large documents may fail |
| Public apps only (free tier) | Anyone with URL can access |
| Apps sleep after inactivity | First load after sleep is slow (~30s) |
| No persistent storage | Output files don't persist between sessions |

For private apps or more resources, Streamlit Cloud has paid tiers.

---

## Troubleshooting

### App crashes on startup
- Check logs: Dashboard → Your app → **"Manage app"** → **"Logs"**
- Common issue: Missing dependency in `requirements.txt`

### "No module named X" error
- Add the missing package to `requirements.txt`
- Push to GitHub → auto-redeploy

### API key not working
- Verify secrets are saved in dashboard
- Check the key name matches exactly (case-sensitive)

### File upload fails
- Check file size (default limit: 200MB)
- Ensure file is a valid `.docx`

---

## Security Considerations

Before sharing the URL publicly:

1. **API Costs:** Anyone with the URL can use your OpenAI API key
   - Consider adding a password or requiring users to input their own key
   
2. **Document Privacy:** Uploaded files pass through Streamlit's servers
   - Not suitable for confidential medical data without additional measures
   
3. **Access Control:** For private access, consider:
   - Streamlit Cloud Teams (paid)
   - Adding simple password protection in the app

---

## Quick Reference

| Action | Command/Location |
|--------|------------------|
| Deploy | share.streamlit.io → New app |
| View logs | Dashboard → Manage app → Logs |
| Add secrets | Settings → Secrets |
| Redeploy | Push to GitHub (automatic) |
| Custom domain | Settings → General (paid plans) |

---

## Future: Migration to Docker

When you outgrow Streamlit Cloud, see the Dockerfile approach in `docs/future_improvements.md`. The app code requires zero changes — just add a Dockerfile.

