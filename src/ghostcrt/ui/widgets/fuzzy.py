from __future__ import annotations

from ghostcrt.models import Host


def subsequence_match(query: str, text: str) -> bool:
    q = query.lower()
    t = text.lower()
    if not q:
        return True
    i = 0
    for ch in t:
        if ch == q[i]:
            i += 1
            if i == len(q):
                return True
    return False


def filter_hosts(hosts: list[Host], query: str) -> list[Host]:
    out: list[Host] = []
    for h in hosts:
        if subsequence_match(query, h.alias) or (
            h.hostname is not None and subsequence_match(query, h.hostname)
        ):
            out.append(h)
    return out
