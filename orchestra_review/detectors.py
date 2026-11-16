"""Groups failures into mistakes: two failures are the same mistake when their last error line matches."""
from collections import defaultdict
import re

# Test runs that fail are the agent checking its work, not a mistake: reproduce scripts fail on purpose.
TEST_OUTCOME=re.compile(r'^(?:AssertionError\b.*|FAILED \(.*|=* ?# failed\b.*|.*\btests? failed\b.*|.*Issue reproduced.*|KeyboardInterrupt|Ran # tests? in .*|# deselected in .*|E +.*)$',re.I)
VOLATILE=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+',re.I)


def signature(step):
    """Two failures are the same mistake when their last error line matches, ignoring ids and numbers.
    The last line is where shells and tracebacks put the actual cause."""
    last=next((line.strip() for line in reversed((step.error or '').splitlines()) if line.strip()),'')
    last=re.sub(r'={2,}','==',VOLATILE.sub('#',last.lstrip('…')))[:160]
    if len(last)<12 or re.fullmatch(r'Exit(ed with)? code #',last): return None  # says nothing about the cause
    if re.fullmatch(r'[~/]\S*',last): return None  # a bare path is output that happened to come last, not a cause
    if TEST_OUTCOME.match(last): return None
    return (step.kind,last)


def by_signature(sessions):
    """Every failed step with a usable signature, grouped by signature and then by session."""
    seen=defaultdict(lambda:defaultdict(list))
    for s in sessions:
        for step in s.steps:
            key=signature(step) if step.ok is False else None
            if key: seen[key][(s.source,s.id)].append(step)
    return seen


def recurring(sessions,minimum=2):
    """Mistakes seen in at least `minimum` sessions, with every failed step that matched them."""
    return sorted(((key,hits) for key,hits in by_signature(sessions).items() if len(hits)>=minimum),
                  key=lambda item:(-len(item[1]),-sum(map(len,item[1].values()))))
