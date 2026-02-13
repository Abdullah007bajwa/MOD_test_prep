"""PrepMaster AI — multi-page exam simulator."""
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure project root is in path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st

from db import get_question_counts, get_questions_by_category, get_questions_by_subcategory, get_subcategory_counts, get_subcategories_by_category
from engine import EXAM_TOTAL, GAT_RATIO, SUBJECT_RATIO, CORRECT_SCORE, INCORRECT_SCORE, SKIPPED_SCORE, EXAM_DURATION_MINUTES
from src.mcq_discovery import get_low_count_subcategories, get_sources_for_subcategory, format_subcategory_name

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
    st.caption("Practice by category or subcategory with immediate feedback and explanations")
    
    # Initialize drill mode session state
    if "drill_category" not in st.session_state:
        st.session_state["drill_category"] = None
    if "drill_subcategory" not in st.session_state:
        st.session_state["drill_subcategory"] = None
    if "drill_questions" not in st.session_state:
        st.session_state["drill_questions"] = []
    if "drill_current_idx" not in st.session_state:
        st.session_state["drill_current_idx"] = 0
    if "drill_answers" not in st.session_state:
        st.session_state["drill_answers"] = {}  # {question_id: selected_idx}
    if "drill_started" not in st.session_state:
        st.session_state["drill_started"] = False
    if "drill_show_discovery" not in st.session_state:
        st.session_state["drill_show_discovery"] = False
    
    # If practice session is active, show practice interface
    if st.session_state["drill_started"] and st.session_state["drill_questions"]:
        questions = st.session_state["drill_questions"]
        answers = st.session_state["drill_answers"]
        current_idx = st.session_state["drill_current_idx"]
        category = st.session_state.get("drill_category", "unknown")
        subcategory = st.session_state.get("drill_subcategory")
        
        if current_idx >= len(questions):
            st.success("You've completed all questions in this practice session!")
            if st.button("Start New Practice Session"):
                st.session_state["drill_started"] = False
                st.session_state["drill_questions"] = []
                st.session_state["drill_current_idx"] = 0
                st.session_state["drill_answers"] = {}
                st.rerun()
            st.stop()
        
        q = questions[current_idx]
        q_id = q.get("id")
        options = q.get("options") or []
        correct_idx = q.get("correct_answer_idx", 0)
        explanation = q.get("explanation", "")
        option_labels = "ABCDEFGHIJ"
        n_opts = min(len(options), 10)
        
        # Check if user has answered this question
        user_answer = answers.get(q_id)
        is_answered = user_answer is not None
        is_correct = is_answered and user_answer == correct_idx
        
        # Show practice mode info
        if subcategory:
            practice_info = f"Practicing: {category.upper()} → {format_subcategory_name(subcategory)}"
        else:
            practice_info = f"Practicing: {category.upper()} (All Questions)"
        
        # Progress indicator
        answered_count = len(answers)
        st.progress((current_idx + 1) / len(questions))
        st.caption(f"{practice_info} | Question {current_idx + 1} of {len(questions)} | {answered_count} answered")
        
        # Question display
        st.subheader("Question")
        st.write(q.get("text", ""))
        
        # Options display
        st.subheader("Options")
        
        if not is_answered:
            # Show radio buttons for selection
            option_display = [f"{option_labels[i]}. {(options[i] or '')}" for i in range(n_opts) if options[i]]
            selected_option = st.radio(
                "Choose your answer:",
                options=list(range(len(option_display))),
                format_func=lambda i: option_display[i] if i < len(option_display) else "",
                key=f"radio_{q_id}"
            )
            
            if st.button("Submit Answer", type="primary"):
                st.session_state["drill_answers"][q_id] = selected_option
                st.rerun()
        else:
            # Show results with color coding
            for i in range(n_opts):
                option_text = options[i] or ""
                if not option_text:
                    continue
                
                label = f"{option_labels[i]}. {option_text}"
                
                # Determine display style
                if i == correct_idx:
                    # Correct answer - highlight in green
                    st.success(f"✓ {label} (Correct Answer)")
                elif i == user_answer and not is_correct:
                    # User's incorrect answer - highlight in red
                    st.error(f"✗ {label} (Your Answer - Incorrect)")
                else:
                    # Other options
                    st.write(f"○ {label}")
        
        # Feedback and explanation (shown after answer)
        if is_answered:
            st.divider()
            if is_correct:
                st.success("✓ Correct! Well done.")
            else:
                st.error(f"✗ Incorrect. The correct answer is {option_labels[correct_idx]}.")
            
            if explanation:
                st.subheader("Explanation")
                st.info(explanation)
            else:
                st.info("No explanation available for this question.")
        
        # Navigation buttons
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("← Previous", disabled=current_idx == 0):
                st.session_state["drill_current_idx"] = current_idx - 1
                st.rerun()
        with col2:
            if st.button("Next →", disabled=current_idx >= len(questions) - 1):
                st.session_state["drill_current_idx"] = current_idx + 1
                st.rerun()
        with col3:
            if st.button("End Practice Session"):
                st.session_state["drill_started"] = False
                st.session_state["drill_questions"] = []
                st.session_state["drill_current_idx"] = 0
                st.session_state["drill_answers"] = {}
                st.rerun()
        
        st.stop()
    
    # Practice session setup UI
    try:
        # Practice mode selection
        practice_mode = st.radio(
            "Practice Mode",
            ["By Category", "By Subcategory"],
            horizontal=True,
            key="drill_practice_mode"
        )
        
        # Category selection
        category = st.radio("Select Category", ["gat", "subject"], horizontal=True, key="drill_category_selector")
        st.session_state["drill_category"] = category
        
        # Get total count for category
        try:
            category_counts = get_question_counts()
            category_total = category_counts.get(category, 0)
        except Exception as e:
            st.warning(f"Could not load category count: {e}")
            category_total = 0
        
        # Practice by Category
        if practice_mode == "By Category":
            st.divider()
            st.subheader(f"Practice All {category.upper()} Questions")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Questions Available", category_total)
            with col2:
                st.info(f"Practice all questions from {category.upper()} category")
            
            if category_total > 0:
                # Option to limit questions
                limit_questions = st.checkbox("Limit number of questions", key="limit_category_questions")
                max_questions = 100
                if limit_questions:
                    max_questions = st.number_input(
                        "Maximum questions to practice",
                        min_value=10,
                        max_value=min(1000, category_total),
                        value=min(100, category_total),
                        step=10,
                        key="category_max_questions"
                    )
                
                if st.button("Start Category Practice Session", type="primary", use_container_width=True):
                    try:
                        # Fetch questions for selected category
                        result = get_questions_by_category(category, limit=max_questions)
                        questions_list = result.data if hasattr(result, 'data') else result
                        
                        if not questions_list:
                            st.error(f"No questions found for {category}")
                        else:
                            # Shuffle questions for variety
                            random.shuffle(questions_list)
                            st.session_state["drill_questions"] = questions_list
                            st.session_state["drill_current_idx"] = 0
                            st.session_state["drill_answers"] = {}
                            st.session_state["drill_started"] = True
                            st.session_state["drill_subcategory"] = None  # Clear subcategory for category practice
                            st.rerun()
                    except Exception as e:
                        st.error(f"Failed to load questions: {e}")
            else:
                st.error(f"No questions available for {category}. Please check the database.")
        
        # Practice by Subcategory
        else:
            st.divider()
            st.subheader("Practice by Subcategory")
            
            # Get subcategories for selected category
            try:
                subcategories = get_subcategories_by_category(category)
            except Exception as e:
                st.error(f"Error loading subcategories: {e}")
                st.stop()
            
            if not subcategories:
                st.warning(f"No subcategories found for {category}. Please ensure questions are loaded in the database.")
                st.stop()
            
            # Get counts for all subcategories
            try:
                subcategory_counts = get_subcategory_counts(category)
                low_count_subs = get_low_count_subcategories(threshold=20, category=category)
            except Exception as e:
                st.warning(f"Could not load subcategory counts: {e}")
                subcategory_counts = {}
                low_count_subs = {}
            
            # Create subcategory options with counts and warnings
            subcategory_options = []
            for sub in sorted(subcategories):
                count = subcategory_counts.get(sub, 0)
                is_low = sub in low_count_subs
                if is_low:
                    display_name = f"{format_subcategory_name(sub)} ({count} questions) ⚠️ Low count"
                else:
                    display_name = f"{format_subcategory_name(sub)} ({count} questions)"
                subcategory_options.append((sub, display_name, count, is_low))
            
            # Subcategory selection
            if subcategory_options:
                selected_display = st.selectbox(
                    "Select Subcategory",
                    options=[opt[0] for opt in subcategory_options],
                    format_func=lambda x: next(opt[1] for opt in subcategory_options if opt[0] == x),
                    key="drill_subcategory_selector"
                )
                st.session_state["drill_subcategory"] = selected_display
                
                # Show selected subcategory info
                selected_info = next(opt for opt in subcategory_options if opt[0] == selected_display)
                selected_count = selected_info[2]
                is_low_count = selected_info[3]
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Available Questions", selected_count)
                with col2:
                    if is_low_count:
                        st.warning(f"⚠️ This subcategory has fewer than 20 questions")
                
                # MCQ Discovery for low-count subcategories
                if is_low_count:
                    st.divider()
                    st.subheader("Find More MCQs Online")
                    st.info(f"Looking for more {format_subcategory_name(selected_display)} questions online...")
                    
                    sources = get_sources_for_subcategory(selected_display)
                    if sources:
                        st.write("**Recommended Sources:**")
                        for source in sources:
                            with st.expander(f"🔗 {source['name']} - {source.get('notes', '')}"):
                                st.write(f"**URL:** [{source['url']}]({source['url']})")
                                if source.get('notes'):
                                    st.caption(f"Note: {source['notes']}")
                    else:
                        st.write("**Search online for:**")
                        search_terms = [
                            f"{format_subcategory_name(selected_display)} MCQs",
                            f"{format_subcategory_name(selected_display)} practice questions",
                            f"{format_subcategory_name(selected_display)} multiple choice questions"
                        ]
                        for term in search_terms:
                            st.write(f"- {term}")
                
                # Start practice button
                if selected_count > 0:
                    if st.button("Start Practice Session", type="primary", use_container_width=True):
                        try:
                            # Fetch questions for selected subcategory
                            result = get_questions_by_subcategory(category, selected_display, limit=100)
                            questions_list = result.data if hasattr(result, 'data') else result
                            
                            if not questions_list:
                                st.error(f"No questions found for {format_subcategory_name(selected_display)}")
                            else:
                                # Shuffle questions for variety
                                random.shuffle(questions_list)
                                st.session_state["drill_questions"] = questions_list
                                st.session_state["drill_current_idx"] = 0
                                st.session_state["drill_answers"] = {}
                                st.session_state["drill_started"] = True
                                st.rerun()
                        except Exception as e:
                            st.error(f"Failed to load questions: {e}")
                else:
                    st.error("No questions available for this subcategory. Please check the database.")
            else:
                st.warning("No subcategories available. Please ensure questions are loaded in the database.")
    
    except Exception as e:
        st.error(f"Error loading drill mode: {e}")
        st.exception(e)
