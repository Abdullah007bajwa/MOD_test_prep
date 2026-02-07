"""PrepMaster AI — multi-page exam simulator."""
import random
import streamlit as st
from datetime import datetime, timedelta

from db import get_question_counts, get_questions_by_category
from engine import EXAM_TOTAL, GAT_RATIO, SUBJECT_RATIO, CORRECT_SCORE, INCORRECT_SCORE, SKIPPED_SCORE, EXAM_DURATION_MINUTES

st.set_page_config(page_title="PrepMaster AI", layout="wide")
st.sidebar.title("PrepMaster AI")
# Allow URL to open a specific page (e.g. after "Start Mock Test")
default_page = st.query_params.get("page", "Dashboard")
if default_page not in ("Dashboard", "Mock Test", "Drill Mode"):
    default_page = "Dashboard"
page = st.sidebar.radio("Navigate", ["Dashboard", "Mock Test", "Drill Mode"], index=["Dashboard", "Mock Test", "Drill Mode"].index(default_page), label_visibility="collapsed")

# ----- Dashboard -----
if page == "Dashboard":
    st.header("Dashboard")
    try:
        counts = get_question_counts()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total questions", counts["total"])
        with col2:
            st.metric("GAT", counts["gat"])
        with col3:
            st.metric("Subject", counts["subject"])
        st.success("Ready for mock test: 70% GAT + 30% Subject (100 MCQs, 120 min).")
        if st.button("Start Mock Test", type="primary", use_container_width=True):
            st.query_params["page"] = "Mock Test"
            st.rerun()
    except Exception as e:
        st.error(f"Could not load question counts. Check DB and .env (SUPABASE_URL, SUPABASE_KEY). {e}")

# ----- Mock Test -----
elif page == "Mock Test":
    st.header("Mock Test")
    st.caption("100 MCQs (70% GAT, 30% Subject) · 120 minutes · Correct +1, Wrong -0.25, Skip 0")

    # Initialize session state for the test
    if "test_started" not in st.session_state:
        st.session_state["test_started"] = False
    if "test_questions" not in st.session_state:
        st.session_state["test_questions"] = []
    if "test_answers" not in st.session_state:
        st.session_state["test_answers"] = {}  # q_index -> selected_index (-1 = skipped)
    if "test_start_time" not in st.session_state:
        st.session_state["test_start_time"] = None
    if "test_submitted" not in st.session_state:
        st.session_state["test_submitted"] = False

    if not st.session_state["test_started"] and not st.session_state["test_submitted"]:
        if st.button("Start exam"):
            try:
                n_gat = int(EXAM_TOTAL * GAT_RATIO)
                n_subject = int(EXAM_TOTAL * SUBJECT_RATIO)
                gat = get_questions_by_category("gat", limit=n_gat * 2).data or []
                subj = get_questions_by_category("subject", limit=n_subject * 2).data or []
                if len(gat) < n_gat or len(subj) < n_subject:
                    st.warning(f"Need at least {n_gat} GAT and {n_subject} Subject questions in DB. Found GAT={len(gat)}, Subject={len(subj)}.")
                else:
                    picked_gat = random.sample(gat, n_gat)
                    picked_subj = random.sample(subj, n_subject)
                    st.session_state["test_questions"] = picked_gat + picked_subj
                    random.shuffle(st.session_state["test_questions"])
                    st.session_state["test_started"] = True
                    st.session_state["test_start_time"] = datetime.utcnow()
                    st.session_state["test_answers"] = {}
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to load questions: {e}")
        st.stop()

    if st.session_state["test_submitted"]:
        st.success("Test submitted. Your score is shown below.")
        # Recompute score from last run
        questions = st.session_state.get("test_questions", [])
        answers = st.session_state.get("test_answers", {})
        score = 0.0
        for i, q in enumerate(questions):
            sel = answers.get(i, -1)
            if sel < 0:
                score += SKIPPED_SCORE
            elif sel == q.get("correct_answer_idx", -2):
                score += CORRECT_SCORE
            else:
                score += INCORRECT_SCORE
        st.metric("Score", f"{score:.2f} / {EXAM_TOTAL}")
        if st.button("Start a new test"):
            st.session_state["test_started"] = False
            st.session_state["test_submitted"] = False
            st.session_state["test_questions"] = []
            st.session_state["test_answers"] = {}
            st.rerun()
        st.stop()

    questions = st.session_state["test_questions"]
    answers = st.session_state["test_answers"]
    start_time = st.session_state["test_start_time"]
    n = len(questions)

    # Progress and timer
    elapsed = (datetime.utcnow() - start_time).total_seconds() if start_time else 0
    remaining_sec = max(0, EXAM_DURATION_MINUTES * 60 - int(elapsed))
    m, s = divmod(remaining_sec, 60)
    st.sidebar.metric("Time left", f"{m}:{s:02d}")
    answered = sum(1 for i in range(n) if answers.get(i, -1) >= 0)
    st.sidebar.progress(answered / n if n else 0)
    st.sidebar.caption(f"Question {answered}/{n} answered")

    # Current question index (persist in session)
    if "current_q" not in st.session_state:
        st.session_state["current_q"] = 0
    idx = st.session_state["current_q"]
    q = questions[idx]
    options = q.get("options") or []
    correct_idx = q.get("correct_answer_idx", 0)
    option_labels = "ABCDEFGHIJ"
    n_opts = min(len(options), 10)

    st.subheader(f"Question {idx + 1} of {n}")
    st.write(q.get("text", ""))

    # options: 0 = Skip, 1..N = A, B, C, ... (up to 10 options; selected 0 -> -1, selected 1 -> 0, etc.)
    opt_indices = [-1] + list(range(n_opts))
    opt_labels = ["— Skip —"] + [f"{option_labels[i]}. {(options[i] or '')[:80]}" for i in range(n_opts)]
    key = f"q_{idx}"
    choice_in_ui = st.radio(
        "Choose one:",
        range(len(opt_indices)),
        format_func=lambda i: opt_labels[i] if i < len(opt_labels) else "",
        key=key,
        index=opt_indices.index(answers.get(idx, -1)) if answers.get(idx, -1) in opt_indices else 0,
    )
    st.session_state["test_answers"][idx] = opt_indices[choice_in_ui]

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Previous") and idx > 0:
            st.session_state["current_q"] = idx - 1
            st.rerun()
    with col2:
        if st.button("Next") and idx < n - 1:
            st.session_state["current_q"] = idx + 1
            st.rerun()
    with col3:
        if st.button("Submit exam"):
            st.session_state["test_submitted"] = True
            st.rerun()

    # Auto-submit when time runs out
    if remaining_sec <= 0:
        st.session_state["test_submitted"] = True
        st.rerun()

# ----- Drill Mode -----
elif page == "Drill Mode":
    st.header("Drill Mode")
    st.info("Weighted practice by weak areas. (Coming soon: uses user_stats for priority.)")
