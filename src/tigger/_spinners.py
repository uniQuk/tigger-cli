"""Weighted, alive-feeling spinner messages for Tigger TUI."""

from __future__ import annotations

import random
import re

# ── Short cat noises ─────────────────────────────────────────────
# Weighted heavily – feel like real cat interrupts.

_NOISES = [
    "mrrp...",
    "mlem...",
    "brrt...",
    "prrr...",
    "mrow?",
    "nya...",
    "chirrp!",
    "ekekekek...",
    "hrrmmm...",
    "boop.",
    "blep.",
    "yeow...",
    "whrrr...",
    "prrt.",
    "mew...",
    "rrrow...",
    "trill~",
    "kekeke...",
    "mmrr...",
    "pfft.",
]

# ── Behaviour-driven lines ──────────────────────────────────────
# Much stronger than generic tech jokes.

_BEHAVIOUR = [
    # Bengal / Tigger personality
    "Tigger is investigating...",
    "Tigger has opinions about this...",
    "High-speed Bengal processing...",
    "Engaging chaos mode...",
    "Too fast. Too curious.",
    "Climbing somewhere he shouldn't...",
    "Knocking something off the desk...",
    "Definitely not helping...",
    "Supervising aggressively...",
    "Demanding attention mid-task...",
    "Sprinting for no reason...",
    "Parkour across the codebase...",

    # Hunting / curiosity
    "Stalking the bug...",
    "Pouncing on the problem...",
    "Chasing a moving pointer...",
    "Tracking suspicious variables...",
    "Sniffing the stack trace...",
    "Listening for hidden errors...",
    "Watching it... waiting...",
    "Calculating the perfect pounce...",
    "Ambushing the solution...",
    "Chattering at a function he can't reach...",
    "Ears back. Focused.",
    "Pupils fully dilated...",

    # Classic cat behaviour
    "Sitting on your keyboard...",
    "Walking across the keys...",
    "Interrupting your workflow...",
    "Sleeping on the important part...",
    "Ignoring you deliberately...",
    "Demanding food (again)...",
    "Staring into nothing...",
    "Judging your code silently...",
    "Pretending not to hear you...",
    "Now it works. You're welcome.",
    "Making biscuits on your keyboard...",
    "Showing you his belly (it's a trap)...",
    "Brought you a dead process...",
    "Knocking your cursor off the edge...",
    "Refusing to move from the warm laptop...",
    "Asserting dominance over the cursor...",
    "Yelling at a closed door...",
    "Third nap of the hour...",
    "Found a bug. Ate it.",
    "Flicking tail disapprovingly...",
    "Zoomies through the call stack...",

    # Boxes / objects
    "Inspecting a box...",
    "Sitting in a smaller box than expected...",
    "Choosing the worst possible place to sit...",
    "Occupying critical infrastructure...",
    "Claiming this as mine...",
    "Wedging into the smallest gap possible...",

    # Cat logic
    "If fits, I sits.",
    "If not fits, still sits.",
    "This was intentional.",
    "Working as designed (cat logic)...",
    "Chaos is optimal.",
    "Solution is somewhere under the couch...",

    # Grooming / idle
    "Grooming mid-operation...",
    "Cleaning nonexistent dust...",
    "Pausing for dramatic effect...",
    "Reconsidering everything...",
    "Buffering thoughts...",

    # Retained / adapted
    "Petting the cat...",
    "Padding softly through your files...",
    "Consulting the whiskers...",
    "Herding digital cats...",
    "Looking for a misplaced semicolon...",
    "Trying to exit Vim (unsuccessfully)...",
]

# ── Light tech puns ─────────────────────────────────────────────
# A few land better than many.

_TECH = [
    "Compiling meowdule...",
    "Running purr-allel processes...",
    "Optimizing purrformance...",
    "Debugging with whiskers...",
    "Caching tuna packets...",
    "Allocating catnip resources...",
    "Forking a new pawcess...",
    "Segfault? hiss...",
    "Garbage collecting hairballs...",
    "Spawning background purrcess...",
    "Reticulating whiskers...",
    "Caching the essentials (mostly cat memes)...",
    "Ensuring the magic smoke stays inside the wires...",
    "Applying percussive paw-maintenance...",
    "Converting tuna into code...",
    "Tail-recursive purring...",
    "Meowlloc failed. Retrying...",
    "Defurragmenting memory...",
    "git push --paws...",
    "cat /dev/random...",
    "chmod 777 treats...",
    "sudo meow...",
]

# ── Mild absurdity ──────────────────────────────────────────────
# Fits LLM latency well.

_ABSURD = [
    "Consulting the litter logs...",
    "Aligning whisker sensors...",
    "Reading ancient cat runes...",
    "Summoning the nap daemon...",
    "Balancing on the edge of reality...",
    "Listening to the void...",
    "The void listens back...",
    "Receiving transmission from the mothership...",
    "The red dot was inside us all along...",
    "Solving P=NP (got distracted)...",
    "Opening a portal behind the sofa...",
    "Transcending to a higher shelf...",
]

# ── Chaos lines (rare, noticeably different) ────────────────────

_CHAOS = [
    "I AM SPEED.",
    "this is fine.",
    "have you tried turning it off and on again?",
    "the code is coming from inside the house...",
    "01101101 01100101 01101111 01110111",
    "ᵐᵉᵒʷ",
    "404: cat not found",
    "AAAAAAAAAAAAAA",
    "you saw nothing.",
    "[object Object]",
    "ˢᵐᵒˡ ᵗʰᵒᵘᵍʰᵗˢ",
    "undefined is not a cat",
]

# ── Weighting ───────────────────────────────────────────────────
# (category, weight) — noises hit hardest, chaos is ~1-2%.

_WEIGHTED_CATEGORIES: list[tuple[list[str], float]] = [
    (_NOISES,    4),
    (_BEHAVIOUR, 3),
    (_TECH,      1),
    (_ABSURD,    1),
    (_CHAOS,     0.15),
]

# ── Noise stretching ────────────────────────────────────────────
# Occasionally stretch repeated consonants: mrrp → mrrrrrp

_STRETCHABLE = re.compile(r"([mrpbwnke])\1+")


def _stretch_noise(msg: str) -> str:
    """Maybe stretch repeated consonants in short noises."""
    if random.random() > 0.3:
        return msg

    def _stretch(m: re.Match[str]) -> str:
        char = m.group(1)
        count = len(m.group(0))
        extra = random.randint(1, 4)
        return char * (count + extra)

    return _STRETCHABLE.sub(_stretch, msg)


# ── Public API ──────────────────────────────────────────────────


def pick_message() -> str:
    """Pick a weighted random spinner message with occasional stretching."""
    categories, weights = zip(*_WEIGHTED_CATEGORIES)
    chosen_cat = random.choices(categories, weights=weights, k=1)[0]
    msg = random.choice(chosen_cat)

    if chosen_cat is _NOISES:
        msg = _stretch_noise(msg)

    return msg
