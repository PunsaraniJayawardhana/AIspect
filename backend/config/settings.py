import os
from dotenv import load_dotenv

load_dotenv()

# Jira
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")          # e.g. https://yourname.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")    # e.g. "EXC"

# LLM providers
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Pipeline config
MODULE2_PASSES = int(os.getenv("MODULE2_PASSES", "5"))
CI_HIGH_THRESHOLD = float(os.getenv("CI_HIGH_THRESHOLD", "0.80"))
CI_MEDIUM_THRESHOLD = float(os.getenv("CI_MEDIUM_THRESHOLD", "0.60"))

# CORS
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")