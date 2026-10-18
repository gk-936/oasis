"""Token and USD metering with hard caps for the final live evaluation. Wraps `LiveLLM._request`, so every real Bedrock call is counted
(cache hits make no call and cost nothing). Nova Pro list prices: USD 0.80 per million input tokens, 3.50 per million output tokens.
The cap is checked BEFORE each call and the run stops at the first cap reached; a call already made is never undone."""
from __future__ import annotations

IN_USD, OUT_USD = 0.80 / 1e6, 3.50 / 1e6


class Meter:
    def __init__(self, cap_tokens: int, cap_usd: float):
        self.cap_tokens, self.cap_usd = cap_tokens, cap_usd
        self.calls = self.tin = self.tout = 0
        self.stopped = ""
        self.log: list[dict] = []

    @property
    def tokens(self) -> int:
        return self.tin + self.tout

    @property
    def usd(self) -> float:
        return self.tin * IN_USD + self.tout * OUT_USD

    def install(self, llm) -> "Meter":
        """Wrap `_request` on one instance, or on the class when given `LiveLLM` itself (chat builds its own instances)."""
        inner = llm._request
        on_class = isinstance(llm, type)

        def metered(*args):
            order, build = args[-2:]
            if self.tokens >= self.cap_tokens or self.usd >= self.cap_usd:
                self.stopped = "token cap" if self.tokens >= self.cap_tokens else "USD cap"
                raise RuntimeError(f"live-run {self.stopped} reached: {self.tokens} tokens, USD {self.usd:.4f}")
            r, m, i = inner(*args)
            u = getattr(r, "usage", None)
            a = int(getattr(u, "prompt_tokens", 0) or getattr(u, "input_tokens", 0) or 0)
            b = int(getattr(u, "completion_tokens", 0) or getattr(u, "output_tokens", 0) or 0)
            if not (a or b):                      # no split reported: count the whole total at the input price (images are mostly input), an upper bound
                a = int(getattr(u, "total_tokens", 0) or 0)
            self.calls += 1
            self.tin += a
            self.tout += b
            self.log.append({"in": a, "out": b, "usd": round(a * IN_USD + b * OUT_USD, 6)})
            return r, m, i

        llm._request = metered
        return self

    def summary(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.tin, "output_tokens": self.tout, "tokens": self.tokens,
                "usd": round(self.usd, 4), "cap_tokens": self.cap_tokens, "cap_usd": self.cap_usd, "stopped_by": self.stopped or None}

    def line(self) -> str:
        return f"{self.calls} calls, {self.tin:,} in + {self.tout:,} out = {self.tokens:,} tokens, USD {self.usd:.4f}"
