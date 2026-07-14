# Discrepancy Taxonomy for Module 2
# Defines all valid discrepancy types and severity mapping

DISCREPANCY_TYPES = [
    "Missing Element",
    "Wrong Label",
    "Business Rule Violation",
    "Layout Constraint Mismatch",
    "Interaction Flow Error"
]

# Severity derived deterministically from discrepancy type
# Not assigned manually - determined by type alone
SEVERITY_MAP = {
    "Missing Element": "HIGH",
    "Wrong Label": "MEDIUM",
    "Business Rule Violation": "HIGH",
    "Layout Constraint Mismatch": "LOW",
    "Interaction Flow Error": "HIGH"
}

# CI Escalation Thresholds
# Grounded in Landis and Koch (1977) inter-rater agreement scale
CI_HIGH = 0.80      # Almost perfect agreement → pass to Module 3
CI_MEDIUM = 0.60    # Substantial agreement → flag for human review
# Below 0.60 = below substantial agreement → discard as hallucination