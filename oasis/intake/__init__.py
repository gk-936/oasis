"""Real inbound channels (email, Telegram) feeding the same pipeline as the pasted-invoice box.

Everything that arrives here is UNTRUSTED text. A channel adds provenance (who sent it, did the sender authenticate) as risk
EVIDENCE; it never adds authority. The pipeline, policy, signed approvals and executor are unchanged.
"""
