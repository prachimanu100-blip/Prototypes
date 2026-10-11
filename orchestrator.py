"""Multi-agent data-quality orchestrator built with LangGraph.

Agents (graph nodes):
    Profiler -> Validator -> [Fixer -> Verifier] (loops) -> Reporter

The Validator's findings drive a conditional route: if nothing can be fixed
automatically the graph skips straight to the Reporter. After every fix pass the
Verifier re-checks the data and either loops back to the Fixer or hands over to
the Reporter. Anything that cannot be fixed safely is escalated for human review.
"""
from __future__ import annotations

import operator
import os
import re
from typing import Annotated, Iterator, TypedDict

import numpy as np
import pandas as pd
from langgraph.graph import END, START, StateGraph

MAX_PASSES = 3
EMAIL_PAT = r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$"
ALIASES = {"Usa": "USA", "Us": "USA", "U.S.": "USA", "Uk": "UK", "Uae": "UAE"}
VALIDITY_TYPES = {"invalid_email", "invalid_date", "out_of_range", "outliers", "inconsistent_format"}
AGE_RANGE = (0, 120)
IQR_MULTIPLIER = 3.0


class State(TypedDict, total=False):
    raw: pd.DataFrame
    df: pd.DataFrame
    use_llm: bool
    profile: dict
    issues: list
    initial_issues: list
    scores_before: dict
    scores_after: dict
    passes: int
    applied: Annotated[list, operator.add]
    log: Annotated[list, operator.add]
    report: str
    report_source: str


# --------------------------------------------------------------------------- #
# Helpers: column typing, issue detection, scoring
# --------------------------------------------------------------------------- #
def _is_text(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def _tokens(col: str) -> set:
    return set(re.split(r"[^a-z0-9]+", col.lower()))


def _kind(col: str, s: pd.Series) -> str:
    t = _tokens(col)
    if "email" in col.lower():
        return "email"
    if "id" in t:
        return "id"
    if "name" in t:
        return "name"
    if pd.api.types.is_datetime64_any_dtype(s) or t & {"date", "time", "timestamp"}:
        return "date"
    if pd.api.types.is_bool_dtype(s):
        return "other"
    if pd.api.types.is_numeric_dtype(s):
        return "age" if "age" in t else "number"
    if _is_text(s) and s.nunique(dropna=True) <= 20:
        return "category"
    return "text"


def _normaliser(col: str, is_cat: bool):
    is_email = "email" in col.lower()

    def f(v):
        if not isinstance(v, str):
            return v
        t = re.sub(r"\s+", " ", v.strip())
        if is_email:
            t = t.lower()
        elif is_cat:
            t = t.title()
            t = ALIASES.get(t, t)
        return t

    return f


def _parse_dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", format="mixed")


def _iqr_bounds(s: pd.Series):
    x = s.dropna()
    q1, q3 = x.quantile(0.25), x.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return q1 - IQR_MULTIPLIER * iqr, q3 + IQR_MULTIPLIER * iqr


def find_issues(df: pd.DataFrame) -> list:
    out: list = []

    def add(kind, col, n, fixable, severity, detail=""):
        if int(n) > 0:
            out.append({"type": kind, "column": col, "count": int(n), "fixable": fixable,
                        "severity": severity, "detail": detail})

    add("duplicate_rows", "(all columns)", df.duplicated().sum(), True, "medium", "Exact duplicate rows")
    for c in df.columns:
        s = df[c]
        k = _kind(c, s)
        add("missing_values", c, s.isna().sum(), k in ("number", "age", "category"), "high",
            "Blank cells" + ("" if k in ("number", "age", "category") else " (no safe automatic fill)"))
        if _is_text(s):
            f = _normaliser(c, k == "category")
            norm = s.map(f)
            add("inconsistent_format", c, (s.notna() & (norm != s)).sum(), True, "low",
                "Extra spaces or inconsistent casing")
            if k == "email":
                ok = norm.fillna("").astype(str).str.match(EMAIL_PAT)
                add("invalid_email", c, (norm.notna() & ~ok).sum(), True, "high", "Not a valid email address")
            if k == "date":
                add("invalid_date", c, (s.notna() & _parse_dates(s).isna()).sum(), True, "high",
                    "Unparseable dates")
        elif k == "age":
            add("out_of_range", c, ((s < AGE_RANGE[0]) | (s > AGE_RANGE[1])).sum(), True, "high",
                f"Outside {AGE_RANGE[0]}-{AGE_RANGE[1]}")
        elif k == "number":
            b = _iqr_bounds(s)
            if b:
                add("outliers", c, ((s < b[0]) | (s > b[1])).sum(), True, "medium",
                    f"Beyond {IQR_MULTIPLIER:g}x IQR")
    return out


def compute_scores(df: pd.DataFrame, issues: list) -> dict:
    """Row-based 0-100 scores: the share of rows free of each kind of problem."""
    rows = max(len(df), 1)
    invalid = sum(i["count"] for i in issues if i["type"] in VALIDITY_TYPES)
    dups = sum(i["count"] for i in issues if i["type"] == "duplicate_rows")
    comp = 100 * (1 - df.isna().any(axis=1).mean()) if len(df) else 100.0
    val = 100 * (1 - min(invalid / rows, 1))
    uniq = 100 * (1 - min(dups / rows, 1))
    return {"completeness": comp, "validity": val, "uniqueness": uniq, "overall": (comp + val + uniq) / 3}


def apply_fixes(df: pd.DataFrame):
    df = df.copy()
    acts: list = []

    def log(action, col, n):
        if int(n) > 0:
            acts.append({"action": action, "column": col, "count": int(n)})

    # 1. Standardise text
    for c in df.columns:
        s = df[c]
        if _is_text(s):
            new = s.map(_normaliser(c, _kind(c, s) == "category"))
            log("Standardised spacing/casing", c, (s.notna() & (new != s)).sum())
            df[c] = new
    # 2. Parse dates (unparseable -> blank, escalated later)
    for c in df.columns:
        s = df[c]
        if _is_text(s) and _kind(c, s) == "date":
            parsed = _parse_dates(s)
            log("Unparseable dates blanked for review", c, (s.notna() & parsed.isna()).sum())
            df[c] = parsed
    # 3. Invalid emails -> blank (never guess an address)
    for c in df.columns:
        s = df[c]
        if _is_text(s) and _kind(c, s) == "email":
            bad = s.notna() & ~s.fillna("").astype(str).str.match(EMAIL_PAT)
            log("Invalid emails blanked for review", c, bad.sum())
            df.loc[bad, c] = np.nan
    # 4. Impossible ages -> blank
    for c in df.columns:
        if _kind(c, df[c]) == "age":
            bad = (df[c] < AGE_RANGE[0]) | (df[c] > AGE_RANGE[1])
            log("Impossible ages blanked", c, bad.sum())
            df.loc[bad, c] = np.nan
    # 5. Duplicates
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    log("Duplicate rows removed", "(all columns)", before - len(df))
    # 6. Outliers: cap to bounds
    for c in df.columns:
        if _kind(c, df[c]) == "number":
            b = _iqr_bounds(df[c])
            if b:
                bad = (df[c] < b[0]) | (df[c] > b[1])
                log("Outliers capped", c, bad.sum())
                df[c] = df[c].clip(b[0], b[1])
    # 7. Impute missing values where it is safe
    for c in df.columns:
        k = _kind(c, df[c])
        n = df[c].isna().sum()
        if n and k in ("number", "age"):
            df[c] = df[c].fillna(df[c].median())
            if k == "age":
                df[c] = df[c].round()
            log("Filled blanks with median", c, n)
        elif n and k == "category" and df[c].notna().any():
            df[c] = df[c].fillna(df[c].mode().iloc[0])
            log("Filled blanks with most common value", c, n)
    return df, acts


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #
def _log(agent: str, msg: str) -> dict:
    return {"agent": agent, "msg": msg}


def profiler(s: State) -> dict:
    df = s["raw"]
    kinds = {c: _kind(c, df[c]) for c in df.columns}
    profile = {"rows": len(df), "columns": len(df.columns), "kinds": kinds}
    return {"df": df.copy(), "profile": profile, "passes": 0, "applied": [],
            "log": [_log("Profiler", f"Profiled {len(df)} rows x {len(df.columns)} columns; "
                                     f"detected column types: {', '.join(sorted(set(kinds.values())))}.")]}


def validator(s: State) -> dict:
    issues = find_issues(s["df"])
    fixable = sum(1 for i in issues if i["fixable"])
    return {"issues": issues, "initial_issues": issues,
            "scores_before": compute_scores(s["df"], issues),
            "scores_after": compute_scores(s["df"], issues),  # overwritten by the Verifier if fixes run
            "log": [_log("Validator", f"Found {len(issues)} issue groups ({fixable} auto-fixable).")]}


def fixer(s: State) -> dict:
    df, acts = apply_fixes(s["df"])
    return {"df": df, "applied": acts,
            "log": [_log("Fixer", f"Pass {s['passes'] + 1}: applied {len(acts)} fixes.")]}


def verifier(s: State) -> dict:
    issues = find_issues(s["df"])
    left = sum(1 for i in issues if i["fixable"])
    return {"issues": issues, "passes": s["passes"] + 1,
            "scores_after": compute_scores(s["df"], issues),
            "log": [_log("Verifier", f"Re-checked data: {left} fixable and "
                                     f"{len(issues) - left} unfixable issue groups remain.")]}


def _facts(s: State) -> dict:
    return {"rows_before": s["profile"]["rows"], "rows_after": len(s["df"]),
            "scores_before": s["scores_before"], "scores_after": s["scores_after"],
            "issues_found": s["initial_issues"], "fixes_applied": s["applied"],
            "needs_human_review": s["issues"]}


def _template_report(f: dict) -> str:
    b, a = f["scores_before"]["overall"], f["scores_after"]["overall"]
    lines = [f"**Data quality improved from {b:.0f} to {a:.0f} out of 100.** "
             f"Rows: {f['rows_before']} before, {f['rows_after']} after cleaning.", "", "**What was fixed**"]
    lines += [f"- {x['action']} in `{x['column']}`: {x['count']}" for x in f["fixes_applied"]] or ["- Nothing needed fixing."]
    lines += ["", "**Needs a human**"]
    lines += [f"- `{x['column']}`: {x['count']} x {x['type'].replace('_', ' ')}. {x['detail']}" for x in f["needs_human_review"]] \
        or ["- Nothing outstanding."]
    return "\n".join(lines)


def _llm_report(f: dict):
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None, "No ANTHROPIC_API_KEY set; used template report."
    try:
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), temperature=0, max_tokens=700)
        prompt = ("You are a data-quality analyst. Using ONLY the JSON below, write a short report in markdown: "
                  "a 2-sentence executive summary, what was fixed, what needs a human and why, and 3 recommendations "
                  "to prevent these issues upstream. Do not invent numbers.\n\n" + str(f))
        out = llm.invoke(prompt).content
        if isinstance(out, list):
            out = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in out)
        return out, "LLM-written report."
    except Exception as e:  # network, auth, missing package...
        return None, f"LLM unavailable ({type(e).__name__}); used template report."


def reporter(s: State) -> dict:
    f = _facts(s)
    text, note = (_llm_report(f) if s.get("use_llm") else (None, "Template report."))
    return {"report": text or _template_report(f), "report_source": note,
            "log": [_log("Reporter", note)]}


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def route_after_validation(s: State) -> str:
    return "fixer" if any(i["fixable"] for i in s["issues"]) else "reporter"


def route_after_verification(s: State) -> str:
    if any(i["fixable"] for i in s["issues"]) and s["passes"] < MAX_PASSES:
        return "fixer"
    return "reporter"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("profiler", profiler), ("validator", validator), ("fixer", fixer),
                     ("verifier", verifier), ("reporter", reporter)]:
        g.add_node(name, fn)
    g.add_edge(START, "profiler")
    g.add_edge("profiler", "validator")
    g.add_conditional_edges("validator", route_after_validation, {"fixer": "fixer", "reporter": "reporter"})
    g.add_edge("fixer", "verifier")
    g.add_conditional_edges("verifier", route_after_verification, {"fixer": "fixer", "reporter": "reporter"})
    g.add_edge("reporter", END)
    return g.compile()


def stream(df: pd.DataFrame, use_llm: bool = False) -> Iterator[tuple]:
    """Yield (node_name, state_update) as each agent finishes."""
    for chunk in build_graph().stream({"raw": df, "use_llm": use_llm}, stream_mode="updates"):
        for node, update in chunk.items():
            yield node, update


def merge(final: dict, update: dict) -> dict:
    for k, v in update.items():
        final[k] = final.get(k, []) + v if k in ("applied", "log") else v
    return final


def run(df: pd.DataFrame, use_llm: bool = False) -> dict:
    final: dict = {"raw": df}
    for _, upd in stream(df, use_llm):
        merge(final, upd)
    return final
