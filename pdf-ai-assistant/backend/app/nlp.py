"""Word-level NLP: tokenization, BM25 keyword search, rank fusion, extractive compression."""
import math
import re
from collections import Counter

STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "will with we our not can which these those their than then also such may more most other "
    "into using used use based".split()
)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-_][a-z0-9]+)*")  # keeps 0.0694, state-of-the-art, c4_loss
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
ABBREV = ("et al.", "e.g.", "i.e.", "fig.", "eq.", "vs.", "cf.")
NUM_HEAD = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z]\.)\s+[A-Z][^.]{2,80}$")
CUES = re.compile(
    r"\b(we (propose|show|find|introduce|present)|in this (paper|survey|work)|results?|"
    r"conclusion|contribution|outperform\w*|significant\w*)\b",
    re.I,
)


def _stem(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokenize(text: str) -> list:
    """Lowercase word tokens, stop words removed, light plural stemming.
    Hyphenated words also yield their parts so 'state-of-the-art' matches 'art'."""
    out = []
    for t in TOKEN_RE.findall(text.lower()):
        parts = [t] + (t.split("-") if "-" in t else [])
        for p in parts:
            if (len(p) > 1 or p.isdigit()) and p not in STOP:
                out.append(_stem(p))
    return out


def is_heading(line: str) -> bool:
    l = line.strip()
    if not (3 <= len(l) <= 90) or l.endswith((".", ",", ";", ":")):
        return False
    if NUM_HEAD.match(l):
        return True
    words = l.split()
    return len(words) <= 10 and (
        l.isupper() or all(w[0].isupper() for w in words if w[0].isalpha() and len(w) > 3)
    )


def split_sentences(text: str) -> list:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or is_heading(line):
            continue
        for s in SENT_RE.split(line):
            s = s.strip()
            if out and out[-1].lower().endswith(ABBREV):
                out[-1] += " " + s
            elif s:
                out.append(s)
    return [s for s in out if len(s) >= 25]


class BM25:
    def __init__(self, docs_tokens: list, k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs_tokens, k1, b
        self.n = len(docs_tokens)
        self.avg = (sum(len(d) for d in docs_tokens) / self.n) if self.n else 1.0
        self.tf = [Counter(d) for d in docs_tokens]
        df = Counter()
        for d in docs_tokens:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query_tokens: list) -> list:
        q = set(query_tokens)
        out = [0.0] * self.n
        for i, (tf, doc) in enumerate(zip(self.tf, self.docs)):
            dl, s = len(doc), 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            out[i] = s
        return out

    def top(self, query_tokens: list, n: int) -> list:
        sc = self.scores(query_tokens)
        return sorted((i for i, s in enumerate(sc) if s > 0), key=lambda i: -sc[i])[:n]


def rrf(rankings: list, k: int = 60) -> list:
    """Reciprocal rank fusion of several ranked id lists."""
    score = {}
    for ranking in rankings:
        for pos, item in enumerate(ranking):
            score[item] = score.get(item, 0.0) + 1.0 / (k + pos + 1)
    return sorted(score, key=score.get, reverse=True)


def build_idf(texts: list) -> dict:
    n = len(texts) or 1
    df = Counter()
    for t in texts:
        df.update(set(tokenize(t)))
    return {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}


def compress(text: str, idf: dict, budget: int) -> str:
    """Extractive summary: page headings plus the highest-scoring sentences, in original order,
    within `budget` characters. No model call, so every page can be covered cheaply."""
    heads = " | ".join([l.strip() for l in text.split("\n") if is_heading(l)][:3])
    scored = []
    for i, s in enumerate(split_sentences(text)):
        toks = tokenize(s)
        if len(toks) < 4:
            continue
        score = sum(idf.get(t, 1.0) for t in set(toks)) / len(toks) ** 0.5
        if CUES.search(s):
            score *= 1.25
        if i == 0:
            score *= 1.1
        scored.append((score, i, s))
    room = max(budget - len(heads), 80)
    chosen, used = [], 0
    for _, i, s in sorted(scored, reverse=True):
        if used + len(s) + 1 <= room:
            chosen.append((i, s))
            used += len(s) + 1
    if not chosen and scored:
        chosen = [(0, max(scored)[2][:room])]
    body = " ".join(s for _, s in sorted(chosen))
    if heads and body:
        return f"{heads}: {body}"
    return heads or body
