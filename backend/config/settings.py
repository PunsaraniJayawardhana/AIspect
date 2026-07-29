import os
from dotenv import load_dotenv

load_dotenv()

# Jira
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")          # e.g. https://yourname.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
DEFAULT_JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODULE1_MODEL = os.getenv("MODULE1_MODEL", "claude-sonnet-4-6")
MODULE2_MODEL = os.getenv("MODULE2_MODEL", "claude-opus-4-7")
MODULE3_MODEL = os.getenv("MODULE3_MODEL", "claude-sonnet-4-6")

# UVRI weights (alpha=coverage, beta=specificity, gamma=ambiguity, delta=testability)
# Defaults to equal weighting. Replace with the values produced by
# backend/scripts/fit_uvri_weights.py once the regression/AHP weight-fitting
# study (human ratings + sub-term scores) has been run.
UVRI_WEIGHT_COVERAGE = float(os.getenv("UVRI_WEIGHT_COVERAGE", "0.0697"))
UVRI_WEIGHT_SPECIFICITY = float(os.getenv("UVRI_WEIGHT_SPECIFICITY", "0.3154"))
UVRI_WEIGHT_AMBIGUITY = float(os.getenv("UVRI_WEIGHT_AMBIGUITY", "0.1685"))
UVRI_WEIGHT_TESTABILITY = float(os.getenv("UVRI_WEIGHT_TESTABILITY", "0.4464"))

# Pipeline config
MODULE2_PASSES = int(os.getenv("MODULE2_PASSES", "5"))
CI_HIGH_THRESHOLD = float(os.getenv("CI_HIGH_THRESHOLD", "0.80"))
CI_MEDIUM_THRESHOLD = float(os.getenv("CI_MEDIUM_THRESHOLD", "0.60"))

# CORS
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
