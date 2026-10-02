"""AI embeddings: turn a job or a CV into 384 numbers that capture its meaning.

Model: all-MiniLM-L6-v2, run with fastembed (ONNX Runtime, no PyTorch), so it
works on a laptop and on a small free server. Two texts about similar work get
vectors pointing the same way; cosine similarity = how close they are (0..1).
"""
import hashlib
import math
import re
import threading
from collections.abc import Sequence
from typing import Optional, Protocol

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_VERSION = "all-MiniLM-L6-v2"
DIMENSIONS = 384
MAX_DESCRIPTION_CHARS = 1200          # the model only reads ~256 words; title + skills go first

_SPACES = re.compile(r"\s+")
_TAGS = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- what text gets embedded
def _clean(text: Optional[str]) -> str:
    return _SPACES.sub(" ", _TAGS.sub(" ", text or "")).strip()


def job_text(title: str, skills: Sequence[str], description: Optional[str]) -> str:
    """Title and skills first (most important), then the start of the description.
    Company name is left out: it says little about what the work is."""
    parts = [_clean(title)]
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    desc = _clean(description)[:MAX_DESCRIPTION_CHARS]
    if desc:
        parts.append(desc)
    return ". ".join(parts)


def cv_text(job_titles: Sequence[str], skills: Sequence[str], education: Optional[str],
            experience_years: Optional[float]) -> str:
    """A short profile built ONLY from the parsed CV fields (never the raw CV text)."""
    parts = []
    if job_titles:
        parts.append(", ".join(job_titles))
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    if education:
        parts.append("Education: " + education)
    if experience_years is not None:
        parts.append(f"{experience_years:g} years of experience" if experience_years else "Fresher")
    return ". ".join(parts)


def text_hash(text: str) -> str:
    """Changes when the text OR the model changes, so we know what must be embedded again."""
    return hashlib.sha256(f"{MODEL_VERSION}\n{text}".encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- the model
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [float(x) / norm for x in vec]


class FastEmbedder:
    """Loads the model once (first use downloads ~90 MB and caches it)."""

    def __init__(self, model_name: str = MODEL_NAME):
        from fastembed import TextEmbedding      # imported here so tests don't need it
        self._model = TextEmbedding(model_name=model_name)
        self._lock = threading.Lock()            # one request at a time uses the model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            vectors = list(self._model.embed(list(texts), batch_size=64))
        return [_normalize(v.tolist()) for v in vectors]


_embedder: Optional[Embedder] = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = FastEmbedder()
    return _embedder


def set_embedder(embedder: Optional[Embedder]) -> None:
    """Tests use this to plug in a small fake model."""
    global _embedder
    _embedder = embedder


def embed_one(text: str) -> list[float]:
    return get_embedder().embed([text])[0]


def embed_cv(job_titles: Sequence[str], skills: Sequence[str], education: Optional[str],
             experience_years: Optional[float]) -> tuple[Optional[str], Optional[str]]:
    """(vector as pgvector text, hash) for a CV, or (None, None) if the CV gave us nothing to match on."""
    if not job_titles and not skills:
        return None, None
    text = cv_text(job_titles, skills, education, experience_years)
    return to_pgvector(embed_one(text)), text_hash(text)


# ---------------------------------------------------------------- database format
def to_pgvector(vec: Sequence[float]) -> str:
    """pgvector accepts text like '[0.1,0.2,...]'; use it with %s::extensions.vector."""
    if len(vec) != DIMENSIONS:
        raise ValueError(f"expected {DIMENSIONS} numbers, got {len(vec)}")
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
