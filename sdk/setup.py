from setuptools import setup, find_packages

setup(
    name="vera-sdk",
    version="1.2.0",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.25.0",
    ],
    extras_require={
        "langchain": ["langchain-core>=0.1.0"],
        "openai": ["openai>=1.0.0"],
        "crewai": ["crewai>=0.1.0"],
        "anthropic": ["anthropic>=0.40.0"],
        "all": [
            "langchain-core>=0.1.0",
            "openai>=1.0.0",
            "crewai>=0.1.0",
            "anthropic>=0.40.0",
        ],
        "dev": [
            "pytest",
            "pytest-asyncio",
            "pytest-httpx",
        ],
    },
    description="Vera — runtime trust layer SDK for AI agents (immutable audit trail, HITL approvals, policy enforcement)",
    python_requires=">=3.10",
)
