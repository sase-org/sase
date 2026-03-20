"""Structured Agentic Software Engineering."""

import warnings

# langchain-core imports pydantic.v1 which is incompatible with Python 3.14+
warnings.filterwarnings(
    "ignore", message="Core Pydantic V1 functionality", category=UserWarning
)

__version__ = "0.1.0"
