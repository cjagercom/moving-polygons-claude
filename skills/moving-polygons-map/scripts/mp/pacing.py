"""Playback timing — a port of app/lib/animation/timeline.ts (getTimeShares etc.).

Playback lasts BASE_MS per transition at 1x. Each transition's share is
proportional to its real time span but floored at MIN_TRANSITION_FRACTION of
an average transition, so clustered keyframes still get a visible morph.
"""

from __future__ import annotations

BASE_MS = 800
MIN_TRANSITION_FRACTION = 0.6


def time_shares(times: list[float]) -> list[float]:
    n = len(times) - 1
    if n < 1:
        return []
    spans = [max(0.0, times[i + 1] - times[i]) for i in range(n)]
    if sum(spans) <= 0:
        return [1 / n] * n
    floor = MIN_TRANSITION_FRACTION / n
    pinned = [False] * n
    while True:
        free_span = sum(s for s, p in zip(spans, pinned) if not p)
        pinned_count = sum(pinned)
        budget = 1 - pinned_count * floor
        changed = False
        for i in range(n):
            if pinned[i]:
                continue
            if free_span <= 0 or (spans[i] / free_span) * budget < floor:
                pinned[i] = True
                changed = True
        if not changed:
            if free_span <= 0:
                return [1 / n] * n
            return [floor if pinned[i] else (spans[i] / free_span) * budget for i in range(n)]


def floored(times: list[float]) -> list[bool]:
    n = len(times) - 1
    if n < 1:
        return []
    floor = MIN_TRANSITION_FRACTION / n
    return [abs(s - floor) < 1e-12 for s in time_shares(times)]


def keyframe_positions(times: list[float]) -> list[float]:
    positions = [0.0]
    acc = 0.0
    for s in time_shares(times):
        acc += s
        positions.append(min(1.0, acc))
    return positions if times else []


def playback_ms(times: list[float]) -> float:
    return BASE_MS * max(0, len(times) - 1)


def time_to_progress(t: float, times: list[float]) -> float:
    if len(times) < 2:
        return 0.0
    pos = keyframe_positions(times)
    if t <= times[0]:
        return 0.0
    for i in range(len(times) - 1):
        if t <= times[i + 1]:
            span = times[i + 1] - times[i]
            f = (t - times[i]) / span if span > 0 else 1.0
            return pos[i] + f * (pos[i + 1] - pos[i])
    return 1.0


def progress_to_time(p: float, times: list[float]) -> float:
    if not times:
        return 0.0
    if len(times) < 2:
        return times[0]
    pos = keyframe_positions(times)
    p = max(0.0, min(1.0, p))
    for i in range(len(times) - 1):
        if p <= pos[i + 1]:
            width = pos[i + 1] - pos[i]
            f = (p - pos[i]) / width if width > 0 else 1.0
            return times[i] + f * (times[i + 1] - times[i])
    return times[-1]
