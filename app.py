import os

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from orchestrator import merge, stream
from sample_data import make_sample

st.set_page_config(page_title="Data-Quality Orchestrator", page_icon="🧹", layout="wide")
st.title("Data-Quality Orchestrator")
st.caption("A LangGraph multi-agent workflow: Profiler, Validator, Fixer, Verifier and Reporter clean a messy dataset "
           "and escalate anything unsafe to automate.")

with st.sidebar:
    st.header("Input")
    source = st.radio("Dataset", ["Sample: messy customers", "Upload a CSV"])
    upload = st.file_uploader("CSV file", type="csv") if source == "Upload a CSV" else None
    st.divider()
    st.header("Report writer")
    key = st.text_input("Anthropic API key (optional)", type="password",
                        help="Only used to write the final report. The cleaning itself needs no LLM.")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    use_llm = st.checkbox("Write the report with an LLM", value=has_key, disabled=not has_key)

if source == "Upload a CSV":
    if upload is None:
        st.info("Upload a CSV in the sidebar to begin.")
        st.stop()
    df = pd.read_csv(upload)
else:
    df = make_sample()

with st.expander(f"Input data: {len(df)} rows x {len(df.columns)} columns", expanded=True):
    st.dataframe(df, width="stretch", height=240)

if st.button("Run agents", type="primary"):
    final: dict = {}
    with st.status("Agents working...", expanded=True) as status:
        for _, update in stream(df, use_llm):
            merge(final, update)
            for entry in update.get("log", []):
                st.write(f"**{entry['agent']}**: {entry['msg']}")
        status.update(label="Agents finished", state="complete")
    st.session_state["final"] = final

final = st.session_state.get("final")
if final:
    b, a = final["scores_before"], final["scores_after"]
    c = st.columns(4)
    c[0].metric("Overall quality", f"{a['overall']:.0f}/100", f"{a['overall'] - b['overall']:+.0f}")
    for col, k in zip(c[1:], ["completeness", "validity", "uniqueness"]):
        col.metric(k.title(), f"{a[k]:.0f}%", f"{a[k] - b[k]:+.0f}")

    t = st.tabs(["Report", "Issues found", "Fixes applied", "Needs human review", "Cleaned data", "Agent trace"])
    with t[0]:
        st.markdown(final["report"])
        st.caption(final["report_source"])
    with t[1]:
        st.dataframe(pd.DataFrame(final["initial_issues"]), width="stretch", hide_index=True)
    with t[2]:
        st.dataframe(pd.DataFrame(final["applied"]), width="stretch", hide_index=True)
    with t[3]:
        if final["issues"]:
            st.warning("These issues have no safe automatic fix. A person should resolve them.")
            st.dataframe(pd.DataFrame(final["issues"]), width="stretch", hide_index=True)
        else:
            st.success("Nothing left for a human to review.")
    with t[4]:
        st.dataframe(final["df"], width="stretch", height=320)
        st.download_button("Download cleaned CSV", final["df"].to_csv(index=False).encode(), "cleaned.csv", "text/csv")
    with t[5]:
        st.dataframe(pd.DataFrame(final["log"]), width="stretch", hide_index=True)
