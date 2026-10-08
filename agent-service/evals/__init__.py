"""Evaluation harness for the FusionPilot agent.

`harness.py` runs a case, `grade.py` judges it, `run_evals.py` is the command line. The split is
deliberate: the grader is a pure function, so it can be tested against deliberately broken runs.
"""
