"""Shared CLI helpers."""
from pathlib import Path

from .config import RulesConfig
from .llm_providers import build_reviewer_chain
from .llm_reviewer import NullReviewer

DEFAULT_CHAIN = "openai,gemini"


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into os.environ (without overriding)."""
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_reviewer(sop_path: Path, cfg: RulesConfig, chain: str, use_llm: bool):
    if not use_llm:
        return NullReviewer(), "off (--no-llm)"
    names = [n.strip() for n in chain.split(",") if n.strip()]
    return build_reviewer_chain(names, sop_path.read_text(encoding="utf-8"), cfg)


def add_llm_args(p) -> None:
    p.add_argument("--llm", default=DEFAULT_CHAIN,
                   help="provider order, first is primary (default: openai,gemini; also: claude)")
    p.add_argument("--no-llm", action="store_true", help="skip the LLM cross-check")
