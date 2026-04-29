"""ScribeMD Health — mock AI scribe vendor (Use Case 1).

Hospitals deploy ScribeMD's agent during physician-patient encounters. The
agent listens, drafts a SOAP note, suggests diagnoses + medication orders,
and queues them for the attending's sign-off. Vera sits between the agent
and the EHR commit: every diagnosis or order routes through HITL approval,
and every step is cryptographically signed in the audit chain.
"""

PRODUCT_NAME = "ScribeMD Health"
VERSION = "0.1.0"
