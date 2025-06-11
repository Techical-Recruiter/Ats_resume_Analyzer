import streamlit as st
import PyPDF2
from docx import Document
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents import set_tracing_disabled
from openai.types.responses import ResponseTextDeltaEvent
import asyncio
import json
import re
import os
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="CV Ranker - Recruiter")

# --- Session State Management for Recruiter App ---
if 'USERS' not in st.session_state:
    st.session_state.USERS = {"admin": {"password": "password123", "email": "admin@example.com", "plan": None}}
if 'logged_in_user' not in st.session_state:
    st.session_state.logged_in_user = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "login_signup"
if 'unregistered_recruiter_cv_count' not in st.session_state:
    st.session_state.unregistered_recruiter_cv_count = 0
if 'processed_resume_names' not in st.session_state:
    st.session_state.processed_resume_names = set()

# Initialize per-user resume count if a logged_in_user exists and it's not the temp recruiter
if st.session_state.logged_in_user and st.session_state.logged_in_user != "recruiter_temp":
    if f"{st.session_state.logged_in_user}_recruiter_resumes_analyzed" not in st.session_state:
        st.session_state[f"{st.session_state.logged_in_user}_recruiter_resumes_analyzed"] = 0
    if f"{st.session_state.logged_in_user}_cooldown_end_time" not in st.session_state:
        st.session_state[f"{st.session_state.logged_in_user}_cooldown_end_time"] = None


# --- Helper Functions (same as before) ---
def input_text(uploaded_file):
    file_name = uploaded_file.name.lower()
    text = ""
    try:
        if file_name.endswith(".pdf"):
            reader = PyPDF2.PdfReader(uploaded_file)
            text = "".join(page.extract_text() for page in reader.pages)
        elif file_name.endswith((".doc", ".docx")):
            doc = Document(uploaded_file)
            text = "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        st.error(f"Error extracting text from {uploaded_file.name}: {str(e)}")
        return ""
    return text

def extract_json_from_response(response_text):
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        try:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            return json.loads(json_match.group()) if json_match else None
        except:
            return None

def display_recruiter_results(data):
    st.subheader("Analysis Results")
    if isinstance(data, dict):
        st.write(f"**JD Match:** {data.get('##JD Match', 'N/A')}")
        st.write("**Matching Keywords:**")
        if matching_keywords := data.get("##Matching Keywords", []):
            st.table(pd.DataFrame({"Matching Keywords": matching_keywords}))
        else:
            st.write("No matching keywords found")
        st.write("**Missing Keywords:**")
        if keywords := data.get("##Missing Keywords", []):
            st.table(pd.DataFrame({"Missing Keywords": keywords}))
        else:
            st.write("No missing keywords found")
        st.write("**Profile Summary:**")
        st.write(data.get("##Profile Summary", "N/A"))
        if "##Years of Experience" in data:
            st.write(f"**Years of Experience:** {data['##Years of Experience']}")
        if "##Key Skill Strengths" in data:
            st.write(f"**Key Skill Strengths:** {', '.join(data['##Key Skill Strengths'])}")
    else:
        st.error("Could not parse response. Raw output:")
        st.code(data)

def display_recruiter_pricing_plans():
    st.header("Pricing Plans (Optional Upgrades)", divider="grey")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Recruiter Free Plan")
        st.markdown("**Free with Restrictions**")
        st.markdown("- Analyze 10 Resumes for Free")
        st.markdown("- Upgrade for More Resumes")
        if st.button("Select Free Recruiter Plan", key="recruiter_free_plan"):
            if st.session_state.logged_in_user and st.session_state.logged_in_user != "recruiter_temp":
                st.session_state.USERS[st.session_state.logged_in_user]["plan"] = "free_recruiter"
                st.session_state.current_page = "recruiter_dashboard"
                st.rerun()
            else:
                st.session_state.logged_in_user = "recruiter_temp" # Allow unregistered access to dashboard
                st.session_state.current_page = "recruiter_dashboard"
                st.rerun()
    with col2:
        st.subheader("Recruiter Basic Plan")
        st.markdown("**Paid Upgrade: $50/month**")
        st.markdown("- Analyze 100 Resumes")
        if st.button("Upgrade to Basic", key="recruiter_basic_plan"):
            st.markdown(
                """
                        <a href="https://pakistanrecruitment.com/" target="_blank" rel="noopener noreferrer" style="text-decoration: none;">
                            <button style="background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer;">
                                Proceed to Payment
                            </button>
                        </a>
                        """,
                unsafe_allow_html=True
            )
    with col3:
        st.subheader("Recruiter Premium Plan")
        st.markdown("**$80/month**")
        st.markdown("- Analyze Unlimited Resumes")
        st.markdown("- Matching & Missing Keywords")
        st.markdown("- Priority Support")
        if st.button("Upgrade to Premium", key="recruiter_premium_plan"):
            st.markdown(
                """
                        <a href="https://pakistanrecruitment.com/" target="_blank" rel="noopener noreferrer" style="text-decoration: none;">
                            <button style="background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer;">
                                Proceed to Payment
                            </button>
                        </a>
                        """,
                unsafe_allow_html=True
            )

async def analyze_resume_recruiter(upload_files, jd, must_have_keywords, good_to_have_keywords, top_n):
    try:
        logged_in_user = st.session_state.logged_in_user
        is_temp_recruiter = logged_in_user == "recruiter_temp"

        if is_temp_recruiter:
            remaining_cvs = 10 - st.session_state.unregistered_recruiter_cv_count
            if len(upload_files) > remaining_cvs:
                st.error(f"You can only analyze {remaining_cvs} more CVs without signing up. Please sign up to continue.")
                return

        file_names = [file.name for file in upload_files]
        duplicate_files = set([name for name in file_names if file_names.count(name) > 1])
        if duplicate_files:
            st.error(f"Duplicate files found: {', '.join(duplicate_files)}. Please remove duplicates and try again.")
            return

        provider = AsyncOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=GEMINI_API_KEY
        )
        model = OpenAIChatCompletionsModel(model="gemini-2.0-flash", openai_client=provider)
        set_tracing_disabled(disabled=True)

        agent = Agent(
            name="ATS Agent",
            instructions="""
            You are a skilled ATS system. You are an experienced Resume analyzer who's has 40 years experience in every tech field. Use your experience and analyze the resume against the job description carefully and provide:
            - Percentage match (e.g., "75%")
            - Missing keywords
            - Matching keywords (keywords from the job description that are present in the resume)
            - Profile summary
            - Candidate's total years of experience
            - Key skill strengths
            Return ONLY valid JSON format: {
                "##JD Match": "X%",
                "##Missing Keywords": [],
                "##Matching Keywords": [],
                "##Profile Summary": "...",
                "##Years of Experience": "Y years",
                "##Key Skill Strengths": ["skill1", "skill2"]
            }
            Keep your response short and complete you response within 100 words. Just be honest about your response because it is the question of company's policy and future i will tip you 20000 dollars for best satisfying responses.
            """,
            model=model,
        )
        if not upload_files:
            st.error("Please upload at least one resume")
            return
        must_have_list = [kw.strip() for kw in must_have_keywords.split(",")] if must_have_keywords else []
        good_to_have_list = [kw.strip() for kw in good_to_have_keywords.split(",")] if good_to_have_keywords else []
        results = []
        comparison_data = []

        resume_count = len(upload_files)
        if not is_temp_recruiter:
            plan = st.session_state.USERS.get(logged_in_user, {}).get("plan")
            limit = 10 if plan == "free_recruiter" else 100 if plan == "basic" else float('inf')
            if plan in ["free_recruiter", "basic"] and st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] + resume_count > limit:
                st.warning(f"You have reached the {limit} resume limit on your current plan. Please upgrade to continue.")
                return

        batch_size = 10
        for batch_idx in range(0, len(upload_files), batch_size):
            batch = upload_files[batch_idx:batch_idx + batch_size]
            st.write(f"Processing batch {batch_idx // batch_size + 1} of {len(upload_files) // batch_size + 1}")
            for idx, upload_file in enumerate(batch, batch_idx + 1):
                st.subheader(f"Analysis for Resume {idx}: {upload_file.name}")
                text = input_text(upload_file)
                if not text:
                    continue
                resume_input = f"Evaluate resume:\n{text}\n\nJob Description:\n{jd}"
                try:
                    result = Runner.run_streamed(starting_agent=agent, input=resume_input)
                    full_response = ""
                    async for event in result.stream_events():
                        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                            full_response += event.data.delta
                    response_json = extract_json_from_response(full_response)
                    if response_json:
                        resume_text = text.lower()
                        # Ensure all must-have keywords are present
                        has_must_have = all(keyword.lower() in resume_text for keyword in must_have_list) if must_have_list else True

                        if has_must_have:
                            # If must-have keywords are present, check for good-to-have
                            has_good_to_have = any(keyword.lower() in resume_text for keyword in good_to_have_list) if good_to_have_list else True
                            if has_good_to_have: # Only include if at least one good-to-have is present
                                response_json["resume_index"] = idx
                                response_json["resume_name"] = upload_file.name
                                results.append(response_json)

                                # Extract data for comparison table
                                experience = response_json.get("##Years of Experience", "N/A")
                                skills = ", ".join(response_json.get("##Key Skill Strengths", []))
                                percentage = response_json.get("##JD Match", "N/A")
                                comparison_data.append({
                                    "Resume Name": upload_file.name,
                                    "Years of Experience": experience,
                                    "Skill Set": skills,
                                    "Match Score": percentage
                                })
                        else:
                            st.warning(f"Resume '{upload_file.name}' skipped: Missing required keywords.")


                except Exception as e:
                    st.error(f"Error analyzing resume {idx}: {str(e)}. Skipping this resume.")
        if not results:
            st.error("No resumes matched the criteria. Please check keywords or upload different resumes.")
        else:
            if is_temp_recruiter:
                st.session_state.unregistered_recruiter_cv_count += len(results)
                remaining_cvs = 10 - st.session_state.unregistered_recruiter_cv_count
                if remaining_cvs <= 0:
                    st.warning("You've reached the limit of 10 CV analyses without an account. Please sign up to continue.")
            else:
                plan = st.session_state.USERS.get(logged_in_user, {}).get("plan")
                if plan in ["free_recruiter", "basic"]:
                    st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] += len(results)
            st.write(f"Total matched resumes: {len(results)}")
            results.sort(key=lambda x: int(x["##JD Match"].replace("%", "")), reverse=True)
            st.subheader(f"Top {top_n} Ranked Resumes")
            for i, result in enumerate(results[:top_n], 1):
                st.subheader(f"Rank {i}: {result['resume_name']}")
                display_recruiter_results(result)
            if len(results) < top_n:
                st.warning(f"Only {len(results)} resumes matched the criteria, less than the requested top {top_n}.")

            if comparison_data:
                st.subheader("Comparison of Qualified Candidates")
                df_comparison = pd.DataFrame(comparison_data)
                df_comparison['Match Score Value'] = df_comparison['Match Score'].str.replace('%', '').astype(int)
                df_comparison = df_comparison.sort_values(by='Match Score Value', ascending=False).drop(columns=['Match Score Value'])
                st.dataframe(df_comparison)

    except Exception as e:
        st.error(f"Server error: {str(e)}. Please try again later.")

# --- Recruiter App UI Logic ---
def recruiter_app():
    if st.session_state.current_page == "login_signup":
        st.title("CV Ranker - Recruiter Access")
        st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
        st.subheader("Welcome Back!")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Sign Up", key="recruiter_signup_button"):
                st.session_state.current_page = "signup_page"
                st.rerun()
        with col2:
            if st.button("Login", key="recruiter_login_button"):
                st.session_state.current_page = "login_page"
                st.rerun()
        st.markdown("---")
        st.subheader("Guest Recruiter Access")
        st.warning(f"No account needed for first 10 CVs. You can analyze {10 - st.session_state.unregistered_recruiter_cv_count} more CVs before signing up.")
        if st.session_state.unregistered_recruiter_cv_count >= 10:
            st.warning("You've reached the limit of 10 CV analyses without an account. Please sign up to continue.")
            if st.button("Sign Up Now (Guest Limit)", key="signup_now_guest_limit"):
                st.session_state.current_page = "signup_page"
                st.rerun()
        else:
            if st.button("Continue as Guest", key="continue_as_guest"):
                st.session_state.logged_in_user = "recruiter_temp"
                st.session_state.current_page = "recruiter_dashboard"
                st.rerun()
        st.markdown("---")
        st.info("To remove limits and access premium features, please sign up.")

    elif st.session_state.current_page == "signup_page":
        st.title("CV Ranker Signup (Recruiter)")
        st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
        username = st.text_input("Username", key="signup_username")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password")
        if st.button("Sign Up", key="signup_action_button"):
            if username and email and password:
                if username not in st.session_state.USERS:
                    st.session_state.USERS[username] = {"password": password, "email": email, "plan": None}
                    st.session_state.logged_in_user = username
                    st.session_state.current_page = "recruiter_pricing"
                    st.rerun()
                else:
                    st.error("Username already exists!")
            else:
                st.error("Please fill all fields!")
        if st.button("Back to Login/Signup", key="signup_back_button"):
            st.session_state.current_page = "login_signup"
            st.rerun()

    elif st.session_state.current_page == "login_page":
        st.title("CV Ranker Login (Recruiter)")
        st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", key="login_action_button"):
            if username in st.session_state.USERS and st.session_state.USERS[username]["password"] == password:
                st.session_state.logged_in_user = username
                if f"{username}_recruiter_resumes_analyzed" not in st.session_state:
                    st.session_state[f"{username}_recruiter_resumes_analyzed"] = 0
                if f"{username}_cooldown_end_time" not in st.session_state:
                    st.session_state[f"{username}_cooldown_end_time"] = None
                st.session_state.current_page = "recruiter_pricing"
                st.rerun()
            else:
                st.error("Invalid username or password")
        st.button("Continue with Google", on_click=lambda: st.warning("Google login not implemented yet!"), key="login_google")
        st.button("Continue with GitHub", on_click=lambda: st.warning("GitHub login not implemented yet!"), key="login_github")
        if st.button("Back to Login/Signup", key="login_back_button"):
            st.session_state.current_page = "login_signup"
            st.rerun()

    elif st.session_state.current_page == "recruiter_pricing":
        logged_in_user = st.session_state.logged_in_user
        st.title("CV Ranker")
        st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
        if logged_in_user and logged_in_user != "recruiter_temp":
            st.write(f"Welcome, {logged_in_user}!")
        display_recruiter_pricing_plans()
        if st.button("Back to Dashboard", key="pricing_to_dashboard_button"):
            st.session_state.current_page = "recruiter_dashboard"
            st.rerun()
        if st.button("Logout", key="pricing_logout_button"):
            st.session_state.logged_in_user = None
            st.session_state.current_page = "login_signup"
            st.rerun()

    elif st.session_state.current_page == "recruiter_dashboard":
        logged_in_user = st.session_state.logged_in_user
        st.title("CV Ranker - Recruiter Dashboard")
        st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
        st.header("Match. Rank. Hire Fast", divider="grey")
        st.markdown('''
            **How to use:**
            1. Upload one or more resumes in PDF, MS Word (.doc, .docx) format.
            2. Paste the job description in the text area.
            3. Enter must-have and good-to-have keywords.
            4. Click Submit to analyze.
        ''')
        top_n = st.number_input("Select top N resumes to rank (up to 5)", min_value=1, max_value=5, value=5)
        must_have_keywords = st.text_area("Enter must-have keywords (comma-separated)", help="e.g., Python, SQL, 5 years")
        good_to_have_keywords = st.text_area("Enter good-to-have keywords (comma-separated)", help="e.g., JavaScript, Cloud")
        jd = st.text_area("Paste job description", height=200)
        upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"],
                                        help="Please upload one or more PDF, MS Word (.doc, .docx) files",
                                        accept_multiple_files=True)
        is_temp_recruiter = logged_in_user == "recruiter_temp"

        if is_temp_recruiter:
            remaining_cvs = 10 - st.session_state.unregistered_recruiter_cv_count
            st.warning(f"Analyze {remaining_cvs} more CVs for free. To remove limits and access premium features, please sign up.")
            if st.button("Sign Up Now", key="dashboard_signup_now"):
                st.session_state.current_page = "signup_page"
                st.rerun()
        else:
            st.write(f"Welcome, {logged_in_user}!")
            user_plan = st.session_state.USERS.get(logged_in_user, {}).get("plan", "Unknown")
            if user_plan == "free_recruiter":
                limit = 10
                current_count = st.session_state.get(f"{logged_in_user}_recruiter_resumes_analyzed", 0)
                st.info(f"Your current plan: {user_plan}. You have analyzed {current_count} resumes. Limit: {limit}.")
            elif user_plan == "basic":
                limit = 100
                current_count = st.session_state.get(f"{logged_in_user}_recruiter_resumes_analyzed", 0)
                st.info(f"Your current plan: {user_plan}. You have analyzed {current_count} resumes. Limit: {limit}.")
            elif user_plan == "premium":
                st.info(f"Your current plan: {user_plan}. You have unlimited analyses.")
            else:
                st.info(f"Your current plan: {user_plan}. Please select a plan from the Pricing page.")


        submit = st.button("Submit")

        if submit:
            if not jd.strip():
                st.error("Please provide a job description to analyze the resumes.")
            else:
                asyncio.run(analyze_resume_recruiter(upload_files, jd, must_have_keywords, good_to_have_keywords, top_n))

        if st.button("Back to Pricing/Logout", key="dashboard_back_to_pricing"):
            st.session_state.current_page = "recruiter_pricing"
            st.rerun()
        if st.button("Logout", key="dashboard_logout_button"):
            st.session_state.logged_in_user = None
            st.session_state.current_page = "login_signup"
            st.rerun()


if __name__ == "__main__":
    recruiter_app()
