import re

TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))
