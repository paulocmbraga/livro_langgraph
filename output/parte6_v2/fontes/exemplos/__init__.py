"""Exemplos da redação iniciada em 16 de outubro de 2026."""
import os

# A bancada local não transmite traces de suas execuções.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
