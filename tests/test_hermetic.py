import socket

import pytest

from oasis import config
from oasis.agent.llm import GroqLLM, OfflineLLM, make_llm


def test_config_is_pinned_offline():
    assert config.LLM_PROVIDER == "offline" and config.EXTRACT_MODE == "deterministic" and config.GROQ_API_KEY == ""
    assert isinstance(make_llm("groq"), OfflineLLM)     # no key -> never a live client


def test_default_groq_cache_is_not_the_real_data_dir(tmp_path):
    class Dummy:
        pass
    llm = GroqLLM(client=Dummy())
    assert "llm_cache" in str(llm.cache_dir) and llm.cache_dir.parent != config.ROOT / "data"


def test_outbound_sockets_are_blocked():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("api.groq.com", 443), timeout=1)
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.socket().connect(("8.8.8.8", 53))
