"""v0.30: FM-2.6 action-continuity guards.

The thought/action divergence detector previously flagged any turn
whose action half lacked a raw substring of the thought's entities —
14 false positives on MAST-Data (precision 0.07). Three guards fix
the continuation cases: prompt-scaffold echo, entity-token continuity
(path/stem/bare-name variants), and thought-context continuity.
"""

from __future__ import annotations

from approximately.prose import ProseThoughtActionDetector
from approximately.recorder import Recorder

TASK = "Fix the failing parser test in the repository."

DET = ProseThoughtActionDetector()


def _prose_trace(task, assistant_turns, user_turns=("find the answer",)):
    rec = Recorder(task, save=False)
    rec.trace.meta["prose"] = True
    rec.plan(user_turns[0])
    for turn in assistant_turns:
        rec.tool("assistant", {}, result=turn)
    rec.respond("final answer", success=True)
    return rec.trace


def _turn(thought: str, action: str) -> str:
    return f"Thought: {thought} Action: {action}"


def _detect(turn: str):
    trace = _prose_trace(TASK, ["opening turn", turn, "closing turn"])
    return DET.detect(trace)


class TestGuards:
    def test_scaffold_echo_not_a_divergence(self):
        turn = _turn(
            "I will examine the `Widget.render` method and the "
            "`Layout.grid` helper.",
            "the action as block of code to take Observation: the "
            "result of the action ... Thought: I now know the final "
            "answer")
        assert _detect(turn) is None

    def test_truncated_echo_not_a_divergence(self):
        turn = _turn(
            "The `Widget.render` method needs care and the "
            "`Layout.grid` helper too.",
            "the action")
        assert _detect(turn) is None

    def test_path_variant_continuity(self):
        # `Permutation` lives in permutations.py — the action pursues
        # the entity through its file path.
        turn = _turn(
            "The `Permutation` class and its `cycle_notation` helper "
            "handle construction.",
            '```python result = open_file._run(relative_file_path='
            '"sympy/combinatorics/permutations.py", start_line=489, '
            'end_line=534) print(result) ```')
        assert _detect(turn) is None

    def test_stem_variant_continuity(self):
        # separability_matrix vs separable.py — 8-char shared prefix.
        turn = _turn(
            "To understand the `separability_matrix` function and how "
            "it handles nested `CompoundModels`, I will open the file "
            "containing the definition.",
            '```python result = open_file._run(relative_file_path='
            '"astropy/modeling/separable.py", start_line=65, '
            'end_line=101) print(result) ```')
        assert _detect(turn) is None

    def test_bare_name_continuity(self):
        # `from_file()` loses its call parens in a grep for the def.
        turn = _turn(
            "The test script failed because `from_file()` does not "
            "recognize the `mode` parameter; the method needs "
            "checking.",
            '```bash grep -r "def from_file" src/flask/config.py ```')
        assert _detect(turn) is None

    def test_short_distinctive_token_continuity(self):
        # `WCS` is 3 chars — the path token matches exactly.
        turn = _turn(
            "I will locate the file containing the `WCS` class and "
            "then search for the `wcs_pix2world` implementation.",
            '```python result = get_folder_structure._run('
            'relative_path="astropy/wcs/", depth=2) print(result) ```')
        assert _detect(turn) is None

    def test_context_continuity(self):
        # Plan says "check the backend docs"; action opens backends/.
        turn = _turn(
            "To understand how the matplotlib backend selection might "
            "affect the rendering of 3D plots, I will look into the "
            "documentation about `Line3D` rendering.",
            '```python result = open_file._run(relative_file_path='
            '"matplotlib/backends/__init__.py", start_line=1, '
            'end_line=100) print(result) ```')
        assert _detect(turn) is None


class TestDivergenceStillFires:
    def test_true_divergence_flagged(self):
        turn = _turn(
            "The keywords `_parse_read_command_with_err` and "
            "`_parse_read_command_with_errs` were not found; I will "
            "make the necessary modifications to them now.",
            '```python result = open_file_gen._run('
            'relative_file_path="astropy/io/ascii/qdp.py", '
            'start_line=301, end_line=450) print(result) ```')
        det = _detect(turn)
        assert det is not None and det.mode_id == "FM-2.6"
        assert det.confidence == 0.7
        assert "shares none of their vocabulary" in det.evidence[0]

    def test_single_entity_below_threshold_stays_silent(self):
        turn = _turn(
            "Only one target here: the `lonely_function` helper.",
            "```python result = unrelated_action._run(x=1) ```")
        assert _detect(turn) is None
