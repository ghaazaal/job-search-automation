"""Market skill analysis and the learning path built from it.

Spec: docs/superpowers/specs/2026-10-14-market-learning-path-design.md

    extract  — Claude reads each posting once; every skill carries a quote
               that must be found in the posting, or it is dropped.
    market   — counting, no model: demand, role families, trends.
    compare  — the resume against that demand; any "you have this" claim
               cites the resume's own words.
    rank     — which gaps matter most, with the reason as countable facts.
    path     — Claude orders the top gaps into stages; it may only plan
               skills the ranking handed it.
    pipeline — runs the five in order and stores one snapshot.
"""
