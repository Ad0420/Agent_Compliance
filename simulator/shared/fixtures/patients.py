"""Synthetic patient generator. HIPAA-safe — never use real PHI here.

Uses Faker with a fixed seed by default so demos are reproducible. Patients
have realistic-shaped fields (DOB, MRN, SSN-shape, address, allergies) so the
SDK's redaction layer has actual targets to scrub.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Optional

from faker import Faker


@dataclass
class Patient:
    """A synthetic patient record. The `subject_id` is what we hand to Vera
    via `data_subject_id` — it's the stable key for GDPR Art. 86 / Colorado
    AI Act subject-access queries."""

    subject_id: str
    mrn: str
    name: str
    date_of_birth: str
    sex: str
    ssn_shape: str
    email: str
    phone: str
    address: str
    allergies: list[str]
    active_medications: list[str]
    chronic_conditions: list[str]
    insurance_id: str

    def to_dict(self) -> dict:
        return asdict(self)

    def safe_summary(self) -> dict:
        """Subset that's always safe to print on a demo screenshare."""
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "dob": self.date_of_birth,
            "sex": self.sex,
            "allergies": self.allergies,
            "active_meds": self.active_medications,
            "chronic_conditions": self.chronic_conditions,
        }


_COMMON_ALLERGIES = [
    "Penicillin",
    "Sulfa drugs",
    "Latex",
    "Peanuts",
    "Shellfish",
    "Aspirin",
    "Iodine contrast",
]
_COMMON_CHRONIC = [
    "Hypertension",
    "Type 2 Diabetes",
    "Hyperlipidemia",
    "Asthma",
    "GERD",
    "Hypothyroidism",
    "Osteoarthritis",
]
_COMMON_MEDS = [
    "Lisinopril 10mg daily",
    "Metformin 500mg BID",
    "Atorvastatin 20mg daily",
    "Albuterol inhaler PRN",
    "Levothyroxine 50mcg daily",
    "Omeprazole 20mg daily",
]


def make_patient(seed: Optional[int] = None) -> Patient:
    """Generate a single synthetic patient. Pass `seed` for reproducibility."""
    fake = Faker("en_US")
    if seed is not None:
        Faker.seed(seed)
        random.seed(seed)

    sex = random.choice(["F", "M"])
    name = fake.name_female() if sex == "F" else fake.name_male()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=89).isoformat()

    return Patient(
        subject_id=f"pt_{fake.uuid4()[:12]}",
        mrn=f"MRN-{fake.random_number(digits=8, fix_len=True)}",
        name=name,
        date_of_birth=dob,
        sex=sex,
        ssn_shape=fake.ssn(),
        email=fake.email(),
        phone=fake.phone_number(),
        address=fake.address().replace("\n", ", "),
        allergies=random.sample(_COMMON_ALLERGIES, k=random.randint(0, 2)),
        active_medications=random.sample(_COMMON_MEDS, k=random.randint(0, 3)),
        chronic_conditions=random.sample(_COMMON_CHRONIC, k=random.randint(0, 2)),
        insurance_id=f"INS-{fake.random_number(digits=10, fix_len=True)}",
    )


def make_patients(count: int, *, base_seed: int = 4242) -> list[Patient]:
    """Generate a deterministic batch of patients."""
    return [make_patient(seed=base_seed + i) for i in range(count)]
