"""How a RimWorld pawn's remembered thoughts add up to mood, and where it breaks: the game's rules, summarised.

Read from the 1.7 game code (November 2026), in our own words:

- A pawn's mood need sits at its base level (0.5) plus the sum of its thoughts' mood offsets, divided by 100.
- A remembered thought (Thought_Memory) offsets mood by its stage's baseMoodEffect, times the moodPowerFactor saved with
  it, plus a saved whole-number moodOffset. When the ThoughtDef sets lerpMoodToZero it fades in a straight line to
  nothing over its duration. A trait the ThoughtDef names in nullifyingTraits (or nullifyingTraitDegrees) cancels it.
- Thoughts of one Def and stage group together (a social memory also needs the same other pawn, and one whose label
  names the other pawn groups only with the same pawn). A group counts its average once at full weight, then each
  further thought at stackedEffectMultiplier (0.75 by default) times the one before.
- Mental breaks: the minor threshold is the pawn's MentalBreakThreshold stat (0.35 in Core, moved by traits); the major
  is 4/7 of it and the extreme 1/7.

What is left out, and said so in every report: situational thoughts (rooms, pain, hunger, cold, darkness, traits,
precepts, drugs' highs) because the save never holds them; stat multipliers on a thought (effectMultiplyingStat) and a
thought worker's own multiplier; cancelling by hediffs, genes, precepts and tales; the threshold's changes from
anything but traits; and the difficulty's mood offset.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .def_lookup import flag, number, text

TICKS_PER_DAY = 60000
MOOD_NEED = "Mood"
MOOD_BASE_LEVEL = 0.5              # NeedDef.baseLevel's default: mood with no thoughts at all
BREAK_THRESHOLD_STAT = "MentalBreakThreshold"
BREAK_THRESHOLD_FALLBACK = 0.35    # Core's base value of that stat, used when the Defs cannot be read
MAJOR_SHARE = 4 / 7                # MentalBreaker.BreakThresholdMajor: threshold x 0.5714286
EXTREME_SHARE = 1 / 7              # MentalBreaker.BreakThresholdExtreme: threshold x 1/7
STACK_MULTIPLIER = 0.75            # ThoughtDef.stackedEffectMultiplier's default
CHEMICAL_NEED_CLASS = "Need_Chemical"
OTHER_PAWN_IN_LABEL = "{0}"        # a label that names the other pawn

RISKS = ("extreme", "major", "minor")


@dataclass
class Stage:
    label: str
    mood: float


@dataclass
class ThoughtRule:
    def_name: str
    label: str
    stages: list                                  # Stage, or None for a stage the Def leaves empty
    social: bool = False
    stack_multiplier: float = STACK_MULTIPLIER
    duration_days: float = 0.0
    lerp_to_zero: bool = False
    stages_stack: bool = False
    nullifying_traits: set = field(default_factory=set)
    nullifying_degrees: set = field(default_factory=set)   # (trait def, degree)


def _tidy(label):
    """A label for a colony-wide list: the other pawn's name dropped ("my husband {0} died" reads "My husband died")."""
    label = (label or "").strip()
    if label.startswith(OTHER_PAWN_IN_LABEL):
        label = "someone" + label[len(OTHER_PAWN_IN_LABEL):]
    label = " ".join(label.replace(OTHER_PAWN_IN_LABEL, "").split())
    return label[:1].upper() + label[1:] if label else label


def thought_rule(element, def_name):
    """A ThoughtDef element (parents merged) as a rule, or None when it has no stages."""
    if element is None:
        return None
    stages = []
    for li in element.findall("stages/li"):
        if li.get("IsNull", "").lower() == "true" or len(li) == 0:
            stages.append(None)
            continue
        stages.append(Stage(text(li, "label") or text(li, "labelSocial") or "", number(li, "baseMoodEffect", 0.0)))
    if not stages:
        return None
    degrees = set()
    for li in element.findall("nullifyingTraitDegrees/li"):
        trait = text(li, "def")
        if trait:
            degrees.add((trait, int(number(li, "degree", 0))))
    thought_class = text(element, "thoughtClass", "")
    return ThoughtRule(
        def_name=def_name, label=text(element, "label", def_name), stages=stages,
        social="Social" in thought_class, stack_multiplier=number(element, "stackedEffectMultiplier", STACK_MULTIPLIER),
        duration_days=number(element, "durationDays", 0.0), lerp_to_zero=flag(element, "lerpMoodToZero"),
        stages_stack=flag(element, "stagesStack"),
        nullifying_traits={li.text.strip() for li in element.findall("nullifyingTraits/li") if li.text and li.text.strip()},
        nullifying_degrees=degrees)


def label_of(rule, stage_index):
    stage = rule.stages[stage_index] if 0 <= stage_index < len(rule.stages) else None
    return _tidy((stage.label if stage else "") or rule.label or rule.def_name)


def memory_mood(rule, stage_index=0, power_factor=None, offset=None, age_ticks=None, duration_override=None):
    """One remembered thought's mood offset, or None when its stage gives no mood (a purely social memory)."""
    stage = rule.stages[stage_index] if 0 <= stage_index < len(rule.stages) else None
    if stage is None or (stage.mood == 0 and not offset):
        return None
    value = stage.mood * (1.0 if power_factor is None else power_factor) + (offset or 0)
    if rule.lerp_to_zero:
        duration = duration_override if duration_override is not None and duration_override >= 0 \
            else rule.duration_days * TICKS_PER_DAY
        if duration > 0:
            value *= 1 - min(max((age_ticks or 0) / duration, 0.0), 1.0)
    return value


def group_key(rule, stage_index, other_pawn):
    """Which thoughts of one pawn the game counts as one group."""
    stage = rule.stages[stage_index] if 0 <= stage_index < len(rule.stages) else None
    raw_label = (stage.label if stage else "") or rule.label or ""
    names_other = OTHER_PAWN_IN_LABEL in raw_label
    other = other_pawn if (rule.social or names_other) else None
    return rule.def_name, None if rule.stages_stack else stage_index, other


def stacked(values, multiplier=STACK_MULTIPLIER):
    """A group's mood: its average at full weight, then each further thought at multiplier times the one before."""
    if not values:
        return 0.0
    weight, step = 0.0, 1.0
    for _ in values:
        weight += step
        step *= multiplier
    return sum(values) / len(values) * weight


def nullified(rule, traits):
    """Whether one of the pawn's traits ({def: degree}) cancels the thought."""
    if any(t in traits for t in rule.nullifying_traits):
        return True
    return any(traits.get(trait) == degree for trait, degree in rule.nullifying_degrees)


def trait_break_change(element, degree):
    """(offset, factor) a trait at a degree applies to the break threshold."""
    if element is None:
        return 0.0, 1.0
    for li in element.findall("degreeDatas/li"):
        if int(number(li, "degree", 0)) == degree:
            return (number(li, f"statOffsets/{BREAK_THRESHOLD_STAT}", 0.0),
                    number(li, f"statFactors/{BREAK_THRESHOLD_STAT}", 1.0))
    return 0.0, 1.0


def thresholds(base, changes=()):
    """(minor, major, extreme) break thresholds from the stat's base value and each trait's (offset, factor)."""
    value = base + sum(offset for offset, _ in changes)
    for _, factor in changes:
        value *= factor
    value = max(value, 0.0)
    return value, value * MAJOR_SHARE, value * EXTREME_SHARE


def risk(level, limits):
    """extreme, major, minor or None: the worst break threshold the mood level is below."""
    minor, major, extreme = limits
    if level < extreme:
        return "extreme"
    if level < major:
        return "major"
    if level < minor:
        return "minor"
    return None


def is_chemical_need(element):
    return element is not None and CHEMICAL_NEED_CLASS in (text(element, "needClass", "") or "")
