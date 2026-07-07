from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def get_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    encoding = get_encoding()
    return len(encoding.encode(text))
