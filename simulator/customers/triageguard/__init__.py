"""TriageGuard — mock telehealth triage vendor (Use Case 3).

Patients describe symptoms to TriageGuard's AI front door. The agent
classifies acuity (self-care | virtual visit | urgent care | ER), a
red-flag detector double-checks for high-risk terms, and Vera routes
borderline cases (low-acuity classifier output AND red-flag fired) to
on-call Nurse Rivera, RN before the patient sees the recommendation.
"""

PRODUCT_NAME = "TriageGuard"
VERSION = "0.1.0"
