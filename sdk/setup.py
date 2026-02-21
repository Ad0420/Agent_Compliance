from setuptools import setup, find_packages

setup(
    name="actionledger",
    version="0.2.0",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.25.0",
    ],
    extras_require={
        "langchain": ["langchain-core>=0.1.0"],
        "openai": ["openai>=1.0.0"],
        "crewai": ["crewai>=0.1.0"],
        "all": [
            "langchain-core>=0.1.0",
            "openai>=1.0.0",
            "crewai>=0.1.0",
        ],
        "dev": [
            "pytest",
            "pytest-asyncio",
            "pytest-httpx",
        ],
    },
    description="SDK for the Action Ledger — immutable audit trail for AI agents",
    python_requires=">=3.10",
)
