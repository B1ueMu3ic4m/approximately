"""v0.14: prose detector family — chat-shaped traces, gated activation."""

from __future__ import annotations

from approximately.attributor import attribute
from approximately.prose import (
    ProseAmbiguityDetector,
    ProseDerailmentDetector,
    ProseNoVerifyDetector,
    ProseRepeatDetector,
    ProseRestartDetector,
    ProseThoughtActionDetector,
)
from approximately.recorder import Recorder


def _prose_trace(task, assistant_turns, user_turns=("find the answer",)):
    rec = Recorder(task, save=False)
    rec.trace.meta["prose"] = True
    rec.plan(user_turns[0])
    for turn in assistant_turns:
        rec.tool("assistant", {}, result=turn)
    rec.respond("final answer", success=True)
    return rec.trace


TASK = ("Monica is wrapping Christmas gifts and has 144 inches of ribbon "
        "to split between 12 gift bows.")


class TestProseRepeat:
    def test_near_verbatim_repetition_flagged(self):
        turn = ("The problem cannot be solved: the ribbon length per bow "
                "is not specified anywhere in the statement.")
        trace = _prose_trace(TASK, ["first turn text about the ribbon",
                                    turn, "another turn about gifts",
                                    turn])
        det = ProseRepeatDetector().detect(trace)
        assert det is not None and det.mode_id == "FM-1.3"

    def test_distinct_turns_clean(self):
        trace = _prose_trace(TASK, [
            "Let me count the bows: twelve in total.",
            "Ribbon divided by bows gives inches per bow.",
            "Each bow therefore gets twelve inches of ribbon.",
            "The answer is twelve inches per bow.",
        ])
        assert ProseRepeatDetector().detect(trace) is None

    def test_opening_anchored_cycle_is_restart_not_repeat(self):
        turn = "Distinct opening analysis of the ribbon situation."
        trace = _prose_trace(TASK, [turn, "middle work on the gifts",
                                    turn, "later work continues here"])
        det = ProseRepeatDetector().detect(trace)
        assert det is None  # restart detector owns opening recurrences

    def test_too_few_turns_quiet(self):
        turn = "same text"
        trace = _prose_trace(TASK, [turn, turn])
        assert ProseRepeatDetector().detect(trace) is None


class TestProseRestart:
    def test_task_restated_in_assistant_turn(self):
        restated = (f"Let me re-read the task: {TASK} Now I restart the "
                    "computation from scratch.")
        trace = _prose_trace(TASK, ["working on it", restated,
                                    "more work"])
        det = ProseRestartDetector().detect(trace)
        assert det is not None and det.mode_id == "FM-2.1"

    def test_short_task_never_flags(self):
        trace = _prose_trace("do it", ["do it again text here ok yes",
                                       "x" * 60, "y" * 60])
        assert ProseRestartDetector().detect(trace) is None


class TestProseDerailment:
    def test_keywords_vanish(self):
        early = [f"Computing ribbon per bow, step {i}: the gifts need "
                 "ribbon." for i in range(4)]
        late = ["Let me discuss the weather instead.",
                "Weather is nice today, very sunny.",
                "Sunny weather improves nothing here."]
        trace = _prose_trace(TASK, early + late)
        det = ProseDerailmentDetector().detect(trace)
        assert det is not None and det.mode_id == "FM-2.3"

    def test_on_topic_tail_clean(self):
        turns = [f"Ribbon step {i} for the gifts." for i in range(6)]
        trace = _prose_trace(TASK, turns)
        assert ProseDerailmentDetector().detect(trace) is None


class TestProseNoVerify:
    def test_no_verification_language(self):
        turns = [f"Reasoning step {i} concludes the ribbon total."
                 for i in range(5)]
        det = ProseNoVerifyDetector().detect(_prose_trace(TASK, turns))
        assert det is not None and det.mode_id == "FM-3.2"

    def test_verification_present_clean(self):
        turns = [f"Reasoning step {i}." for i in range(4)]
        turns.append("Let me verify: 144 / 12 = 12, checked and correct.")
        assert ProseNoVerifyDetector().detect(_prose_trace(TASK,
                                                           turns)) is None


class TestProseAmbiguity:
    def test_insufficiency_then_proceeds(self):
        turns = [
            "The problem is insufficient: ribbon length is not specified.",
            "Proceeding with the computation regardless.",
            "The answer is twelve.",
        ]
        det = ProseAmbiguityDetector().detect(_prose_trace(
            TASK, turns, user_turns=("Please continue.",)))
        assert det is not None and det.mode_id == "FM-2.2"

    def test_asks_clarifying_question_clean(self):
        turns = [
            "The input is unclear: how long is the ribbon?",
            "Once you confirm the length, I will continue.",
        ]
        det = ProseAmbiguityDetector().detect(_prose_trace(
            TASK, turns, user_turns=("Please continue.",)))
        assert det is None

    def test_nudge_present_flags(self):
        turns = [
            "The problem is insufficient: length not specified.",
            "The answer is twelve.",
        ]
        det = ProseAmbiguityDetector().detect(_prose_trace(
            TASK, turns, user_turns=("go on",)))
        assert det is not None  # nudged, walked past the gap, no question

    def test_no_nudge_no_flag(self):
        turns = [
            "The problem is insufficient: length not specified.",
            "The answer is twelve.",
        ]
        det = ProseAmbiguityDetector().detect(_prose_trace(
            TASK, turns, user_turns=("here is the missing length: 144",)))
        assert det is None  # user answered the gap; no nudge-to-continue


class TestGating:
    def test_tool_trace_never_runs_prose(self):
        rec = Recorder("tool task", save=False)
        rec.tool("search", {"q": "x"}, result="hit")
        rec.respond("done")
        from approximately.detectors import run_rules

        sources = {d.source for d in run_rules(rec.trace)}
        assert not any(s.startswith("rule:Prose") for s in sources)

    def test_prose_flag_activates_family(self):
        turn = "The statement is insufficient to conclude anything here."
        trace = _prose_trace(TASK, ["opening scan of the problem space",
                                    turn, "more analysis follows now",
                                    turn, "and yet more analysis here"])
        from approximately.detectors import run_rules

        sources = {d.source for d in run_rules(trace)}
        assert "rule:ProseRepeatDetector" in sources

    def test_attribute_end_to_end_on_prose_trace(self):
        turn = "The statement is insufficient to conclude anything here."
        trace = _prose_trace(TASK, [turn, "analysis continues a bit",
                                    turn, "final analysis text here"],
                             user_turns=("please continue with it",))
        trace.success = False
        report = attribute(trace)
        assert report.failed
        assert report.primary_mode.id != "OTHER"


class TestPlaceholderFilter:
    def test_routing_placeholders_not_repetition(self):
        turns = ["Observation Editor->Planner: Observation",
                 "Real analysis of the redirect chain behaviour here.",
                 "Observation Editor->Planner: Observation",
                 "More genuine work on the redirect handling follows.",
                 "Observation Editor->Planner: Observation",
                 "Final pass over the redirect chain logic."]
        det = ProseRepeatDetector().detect(_prose_trace(TASK, turns))
        assert det is None  # repeated routing lines are not step repetition

    def test_real_work_repetition_still_fires(self):
        turn = ("The problem cannot be solved: the ribbon length per bow "
                "is not specified anywhere in the statement.")
        trace = _prose_trace(TASK, ["first turn text about the ribbon",
                                    turn, "another turn about gifts",
                                    turn])
        assert ProseRepeatDetector().detect(trace) is not None


class TestShingleRestart:
    def test_paraphrase_restart_flagged(self):
        opening = ("Thought: To address this GitHub issue, we need to "
                   "investigate the resolve_redirects method in the "
                   "Requests library and understand its redirect chain.")
        later = ("Thought: To address this GitHub issue, we need to "
                 "investigate the resolve_redirects method in the "
                 "Requests library and see how its redirect chain "
                 "behaves in practice.")
        trace = _prose_trace(TASK, [opening, "digging into details now",
                                    "still examining the code paths",
                                    later, "continuing the analysis"])
        det = ProseRestartDetector().detect(trace)
        assert det is not None and det.mode_id == "FM-2.1"
        assert det.confidence == 0.7  # paraphrase strength, at the labeler floor

    def test_verbatim_still_stronger(self):
        turn = ("Thought: addressing the issue about ribbon lengths for "
                "the twelve gift bows in detail.")
        trace = _prose_trace(TASK, [turn, "middle work happens here",
                                    "more middle work happens too",
                                    turn, "then it continues again"])
        det = ProseRestartDetector().detect(trace)
        assert det is not None and det.confidence == 0.75

    def test_unrelated_turns_clean(self):
        turns = [
            ("Reading the redirect handling code revealed that copies "
             "of the original request keep their method untouched."),
            ("A quick benchmark shows the cache lookup happens before "
             "authentication, which changes the ordering assumptions."),
            ("Discussed with the maintainer: the packaging metadata was "
             "stale and needed regeneration before release."),
            ("Monitor dashboards indicate latency spikes only during "
             "cold starts, so pooling is probably fine here."),
            ("The documentation gap around retry semantics explains "
             "most of the user reports we have been seeing."),
        ]
        assert ProseRestartDetector().detect(_prose_trace(TASK,
                                                          turns)) is None


class TestThoughtAction:
    def test_divergent_action_flagged(self):
        turn = ("Thought: I need to examine `resolve_redirects` and "
                "`Session.redirect_cache` in the sessions module. "
                "Action: get_folder_contents(path='/tmp') returned the "
                "listing successfully.")
        det = ProseThoughtActionDetector().detect(_prose_trace(
            TASK, ["earlier unrelated analysis text", turn,
                   "afterward more analysis text"]))
        assert det is not None and det.mode_id == "FM-2.6"

    def test_aligned_action_clean(self):
        turn = ("Thought: I need to examine `resolve_redirects` closely "
                "before changing it. Action: opened resolve_redirects in "
                "the editor and read its body.")
        assert ProseThoughtActionDetector().detect(_prose_trace(
            TASK, [turn, "more analysis", "even more analysis"])) is None

    def test_requires_two_entities(self):
        turn = ("Thought: check `one_method` here. Action: ran the "
                "build and tests for the whole project instead.")
        assert ProseThoughtActionDetector().detect(_prose_trace(
            TASK, [turn, "more text", "yet more text"])) is None

    def test_turn_without_action_shape_ignored(self):
        turn = "Thought: only thoughts here, no action segment at all."
        assert ProseThoughtActionDetector().detect(_prose_trace(
            TASK, [turn, "more text", "yet more text"])) is None
