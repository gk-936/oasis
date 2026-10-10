import os

# Tests never touch the real SQLite file: the API session is in-memory unless a test builds its own Session.
os.environ["OASIS_DB"] = ":memory:"
os.environ.setdefault("OASIS_LLM", "offline")
