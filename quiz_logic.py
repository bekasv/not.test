import json
import random
from collections import defaultdict
from typing import List, Dict
from models import Question

TEST_SIZE = 120

def parse_correct(s: str) -> List[int]:
    return list(json.loads(s))

def select_questions_strict(questions: List[Question]) -> List[Question]:
    # group by theme_id
    by_theme: Dict[int, List[Question]] = defaultdict(list)
    pick_by_theme: Dict[int, int] = {}
    for q in questions:
        by_theme[q.theme_id].append(q)
        pick_by_theme[q.theme_id] = q.pick_count

    total_quota = sum(pick_by_theme.values())
    if total_quota != TEST_SIZE:
        raise ValueError("CONFIG_QUOTA_NOT_120")

    selected: List[Question] = []
    for theme_id, pool in by_theme.items():
        pick = pick_by_theme.get(theme_id, 0)
        if pick <= 0:
            continue
        if len(pool) < pick:
            raise ValueError("INSUFFICIENT_QUESTIONS")
        selected.extend(random.sample(pool, pick))

    random.shuffle(selected)
    if len(selected) != TEST_SIZE:
        raise ValueError("BAD_SELECTION")
    return selected

def is_correct(q: Question, selected: List[int]) -> bool:
    correct = set(parse_correct(q.correct_json))
    if q.qtype == "single_choice":
        return len(selected) == 1 and len(correct) == 1 and selected[0] in correct
    return set(selected) == correct
