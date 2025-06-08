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
from datetime import datetime, timedelta
import pandas as pd 
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
st.set_page_config(page_title="CV Ranker by Pakistan Recruitment")

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

def display_results(data):
    st.subheader("Analysis Results")
    if isinstance(data, dict):
        st.write(f"**JD Match:** {data.get('##JD Match', 'N/A')}")
        st.write("**Matching Keywords:**")
        if matching_keywords := data.get("##Matching Keywords", []):
            st.table(matching_keywords)
        else:
            st.write("No matching keywords found")
        st.write("**Missing Keywords:**")
        if keywords := data.get("##Missing Keywords", []):
            st.table(keywords)
        else:
            st.write("No missing keywords found")
        st.write("**Profile Summary:**")
        st.write(data.get("##Profile Summary", "N/A"))
    else:
        st.error("Could not parse response. Raw output:")
        st.code(data)

def display_pricing_plans():
    st.header("Pricing Plans (Optional Upgrades)", divider="grey")
    st.markdown("Both Job Seeker and Recruiter roles are free with restrictions. Upgrade for more features!")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Job Seeker Free Plan")
        st.markdown("**Free Forever**")
        st.markdown("- Unlimited Job Description Matching")
        st.markdown("- Profile Summary")
        st.markdown("- Matching & Missing Keywords")
        if st.button("Select Free Plan", key="job_seeker_plan"):
            st.session_state.USERS[st.session_state.logged_in_user]["plan"] = "free"
            st.session_state.user_role = "Job Seeker"
            st.session_state.current_page = "job_seeker_dashboard"
            st.session_state.page_history.append("job_seeker_dashboard")
            st.rerun()
    with col2:
        st.subheader("Recruiter Free Plan")
        st.markdown("**Free with Restrictions**")
        st.markdown("- Analyze 10 Resumes for Free")
        st.markdown("- Upgrade for More Resumes")
        st.markdown("**Paid Upgrade: $50/month**")
        st.markdown("- Analyze 100 Resumes")
        if st.button("Select Free Recruiter Plan", key="recruiter_free_plan"):
            st.session_state.USERS[st.session_state.logged_in_user]["plan"] = "free_recruiter"
            st.session_state.current_page = "recruiter_dashboard"
            st.session_state.page_history.append("recruiter_dashboard")
            st.rerun()
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

if 'USERS' not in st.session_state:
    st.session_state.USERS = {"admin": {"password": "password123", "email": "admin@example.com", "plan": None}}
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'logged_in_user' not in st.session_state:
    st.session_state.logged_in_user = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "role_selection"
if 'page_history' not in st.session_state:
    st.session_state.page_history = ["role_selection"]
if 'unregistered_recruiter_cv_count' not in st.session_state:
    st.session_state.unregistered_recruiter_cv_count = 0
if 'processed_resume_names' not in st.session_state:
    st.session_state.processed_resume_names = set()

if st.session_state.current_page == "role_selection":
    st.title("CV Ranker")
    st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
    st.header("Select Your Role")
    user_role = st.selectbox("Are you a:", ["Job Seeker", "Recruiter"])
    if st.button("Continue"):
        st.session_state.role_selected = True
        st.session_state.user_role = user_role
        if user_role == "Job Seeker":
            st.session_state.USERS["job_seeker_temp"] = {"password": None, "email": None, "plan": "free"}
            st.session_state.logged_in_user = "job_seeker_temp"
            st.session_state.current_page = "job_seeker_dashboard"
            st.session_state.page_history.append("job_seeker_dashboard")
        else:
            if st.session_state.unregistered_recruiter_cv_count >= 10:
                st.warning("You've reached the limit of 10 CV analyses without an account. Please sign up to continue.")
                st.session_state.current_page = "recruiter_signup"
                st.session_state.page_history.append("recruiter_signup")
            else:
                st.session_state.logged_in_user = "recruiter_temp"
                st.session_state.current_page = "recruiter_dashboard"
                st.session_state.page_history.append("recruiter_dashboard")
        st.rerun()

elif st.session_state.current_page == "job_seeker_dashboard":
    logged_in_user = st.session_state.logged_in_user
    st.title("CV Ranker")
    st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
    st.write("Welcome!")

    st.header("Match your CV with any Job Post in seconds.", divider="grey")
    st.markdown('''
        **How to use:**
        1. Upload your resume in PDF, MS Word (.doc, .docx) format.
        2. Paste the job description in the text area.
        3. Click Submit to analyze.
    ''')

    upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"],
                                    help="Please upload one or more PDF, MS Word (.doc, .docx) files",
                                    accept_multiple_files=False)
    jd = st.text_area("Paste job description", height=200)
    submit = st.button("Submit")

    if st.button("Back"):
        st.session_state.page_history.pop()
        st.session_state.current_page = st.session_state.page_history[-1] if st.session_state.page_history else "role_selection"
        st.rerun()

    async def analyze_resume_basic(upload_files, jd):
        try:
            provider = AsyncOpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=GEMINI_API_KEY
            )
            model = OpenAIChatCompletionsModel(model="gemini-2.0-flash", openai_client=provider)
            set_tracing_disabled(disabled=True)

            agent = Agent(
                name="ATS Agent",
                instructions="""
                You are a career counselor analyzing a resume against a job description. Provide detailed feedback in this EXACT JSON format:
                
                {
                    "##JD Match": "X%",
                    "##Matching Keywords": ["keyword1", "keyword2"],
                    "##Missing Keywords": ["keyword3", "keyword4"],
                    "##Qualifications Analysis": {
                        "Experience Comparison": "JD requires X years, candidate has Y years (Overqualified/Underqualified/Good match)",
                        "Education Match": "How well the education matches (Excellent/Good/Fair/Poor)",
                        "Skill Gaps": ["List of important skills missing"],
                        "Strengths": ["List of strong matching skills"]
                    },
                    "##Improvement Suggestions": {
                        "Key Areas": ["List 2-3 key areas needing improvement"],
                        "Actionable Advice": ["Specific actionable advice for each area"],
                        "Career Fit": "How well the candidate fits this role (Excellent/Good/Fair/Poor)"
                    },
                    "##Profile Summary": "Concise 50-word summary of fit and key recommendations"
                }
                
                Analyze thoroughly and provide:
                1. Precise comparison of required vs actual experience years
                2. Detailed education/qualification matching
                3. Specific skill gaps and strengths
                4. Actionable improvement advice
                5. Honest assessment of over/under qualification
                6. Clear career fit assessment
                7. Act like you are talking straight to the job seeker
                
                Keep your response short and effective as much as possible. Be brutally honest but constructive. Focus on helping the candidate improve.
                """,
                model=model,
            )

            if not upload_files or len([upload_files]) != 1:
                st.error("Please upload exactly one resume")
                return False

            upload_file = upload_files
            st.subheader(f"Analysis for Resume: {upload_file.name}")
            text = input_text(upload_file)
            if not text:
                return False

            resume_input = f"Resume Content:\n{text}\n\nJob Description:\n{jd}"
            result = Runner.run_streamed(starting_agent=agent, input=resume_input)
            full_response = ""
            async for event in result.stream_events():
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    full_response += event.data.delta

            response_json = extract_json_from_response(full_response)
            if response_json:
                display_enhanced_results(response_json)
                return True
            else:
                return False
        except Exception as e:
            st.error(f"Server error: {str(e)}. Please try again later.")
            return False

    def display_enhanced_results(data):
        st.subheader("Detailed Analysis Results")

        if isinstance(data, dict):
            st.write(f"**Overall JD Match Score:** {data.get('##JD Match', 'N/A')}")

            st.subheader("Qualifications Breakdown", divider="blue")
            quals = data.get("##Qualifications Analysis", {})

            st.write(f"**Experience Match:** {quals.get('Experience Comparison', 'N/A')}")
            st.write(f"**Education Match:** {quals.get('Education Match', 'N/A')}")

            st.write("**Strengths:**")
            if strengths := quals.get("Strengths", []):
                for strength in strengths:
                    st.success(f"✓ {strength}")
            else:
                st.write("No key strengths identified")

            st.write("**Skill Gaps:**")
            if gaps := quals.get("Skill Gaps", []):
                for gap in gaps:
                    st.error(f"✗ {gap}")
            else:
                st.info("No major skill gaps identified")

            st.subheader("Career Improvement Advice", divider="green")
            improvements = data.get("##Improvement Suggestions", {})

            st.write("**Key Areas Needing Improvement:**")
            if areas := improvements.get("Key Areas", []):
                for area in areas:
                    st.warning(f"⚠ {area}")
            else:
                st.info("No major improvement areas identified")

            st.write("**Actionable Advice:**")
            if advice := improvements.get("Actionable Advice", []):
                for item in advice:
                    st.info(f"• {item}")
            else:
                st.write("No specific advice available")

            st.write(f"**Overall Career Fit:** {improvements.get('Career Fit', 'N/A')}")

            st.subheader("Keyword Analysis", divider="orange")

            col1, col2 = st.columns(2)
            with col1:
                st.write("**Matching Keywords:**")
                if matching := data.get("##Matching Keywords", []):
                    st.table(matching)
                else:
                    st.write("None found")

            with col2:
                st.write("**Missing Keywords:**")
                if missing := data.get("##Missing Keywords", []):
                    st.table(missing)
                else:
                    st.write("None found")

            st.subheader("Career Counselor's Summary", divider="blue")
            st.write(data.get("##Profile Summary", "No summary available"))

        else:
            st.error("Could not parse response. Raw output:")
            st.code(data)

    if submit:
        if not jd.strip():
            st.error("Please provide a job description to analyze the resume.")
        else:
            success = asyncio.run(analyze_resume_basic(upload_files, jd))

elif st.session_state.current_page == "recruiter_signup":
    if "show_login" not in st.session_state:
        st.session_state.show_login = False
    st.title("CV Ranker Signup (Recruiter)")
    st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
    if not st.session_state.show_login:
        username = st.text_input("Username")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Sign Up"):
            if username and email and password:
                if username not in st.session_state.USERS:
                    st.session_state.USERS[username] = {"password": password, "email": email, "plan": None}
                    st.session_state.show_login = True
                    st.session_state.current_page = "recruiter_login"
                    if "recruiter_signup" in st.session_state.page_history:
                        st.session_state.page_history.append("recruiter_login")
                    st.rerun()
                else:
                    st.error("Username already exists!")
            else:
                st.error("Please fill all fields!")
    if st.button("Back"):
        st.session_state.page_history.pop()
        st.session_state.current_page = st.session_state.page_history[-1] if st.session_state.page_history else "role_selection"
        st.session_state.show_login = False
        st.rerun()

elif st.session_state.current_page == "recruiter_login":
    st.title("CV Ranker Login (Recruiter)")
    st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username in st.session_state.USERS and st.session_state.USERS[username]["password"] == password:
            st.session_state.logged_in_user = username
            if f"{username}_recruiter_resumes_analyzed" not in st.session_state:
                st.session_state[f"{username}_recruiter_resumes_analyzed"] = 0
            if f"{username}_cooldown_end_time" not in st.session_state:
                st.session_state[f"{username}_cooldown_end_time"] = None
            st.session_state.current_page = "recruiter_pricing"
            st.session_state.page_history.append("recruiter_pricing")
            st.session_state.show_login = False
            st.rerun()
        else:
            st.error("Invalid username or password")
    st.button("Continue with Google", on_click=lambda: st.warning("Google login not implemented yet!"))
    st.button("Continue with GitHub", on_click=lambda: st.warning("GitHub login not implemented yet!"))
    if st.button("Back"):
        st.session_state.page_history.pop()
        st.session_state.current_page = st.session_state.page_history[-1] if st.session_state.page_history else "role_selection"
        st.session_state.show_login = False
        st.rerun()

elif st.session_state.current_page == "recruiter_pricing":
    logged_in_user = st.session_state.logged_in_user
    st.title("CV Ranker")
    st.markdown("**Powered by PakistanRecruitment**", unsafe_allow_html=True)
    if logged_in_user != "recruiter_temp":
        st.write(f"Welcome, {logged_in_user}!")
    display_pricing_plans()
    if st.button("Back"):
        st.session_state.page_history.pop()
        st.session_state.current_page = st.session_state.page_history[-1] if st.session_state.page_history else "role_selection"
        st.rerun()

elif st.session_state.current_page == "recruiter_dashboard":
    logged_in_user = st.session_state.logged_in_user
    st.title("CV Ranker")
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
        if st.button("Sign Up Now"):
            st.session_state.current_page = "recruiter_signup"
            st.session_state.page_history.append("recruiter_signup")
            st.rerun()
    else:
        st.write(f"Welcome, {logged_in_user}!")
        plan = st.session_state.USERS[logged_in_user]["plan"]
        if plan in ["free_recruiter", "basic"] and f"{logged_in_user}_recruiter_resumes_analyzed" not in st.session_state:
            st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] = 0
        elif plan == "premium" and f"{logged_in_user}_recruiter_resumes_analyzed" not in st.session_state:
            st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] = 0
    submit = st.button("Submit")
    if st.button("Back"):
        st.session_state.page_history.pop()
        st.session_state.current_page = st.session_state.page_history[-1] if st.session_state.page_history else "role_selection"
        st.rerun()

    async def analyze_resume_advanced():
        try:
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
                plan = st.session_state.USERS[logged_in_user]["plan"]
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
                            has_must_have = any(keyword.lower() in resume_text for keyword in must_have_list) if must_have_list else True
                            if has_must_have:
                                has_good_to_have = any(keyword.lower() in resume_text for keyword in good_to_have_list) if good_to_have_list else True
                                if has_good_to_have:
                                    response_json["resume_index"] = idx
                                    response_json["resume_name"] = upload_file.name
                                    results.append(response_json)

                                    experience = response_json.get("##Years of Experience", "N/A")
                                    skills = ", ".join(response_json.get("##Key Skill Strengths", []))
                                    percentage = response_json.get("##JD Match", "N/A")
                                    comparison_data.append({
                                        "Resume Name": upload_file.name,
                                        "Years of Experience": experience,
                                        "Skill Set": skills,
                                        "Match Score": percentage
                                    })

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
                    if plan in ["free_recruiter", "basic"]:
                        st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] += len(results)
                st.write(f"Total matched resumes: {len(results)}")
                results.sort(key=lambda x: int(x["##JD Match"].replace("%", "")), reverse=True)
                st.subheader(f"Top {top_n} Ranked Resumes")
                for i, result in enumerate(results[:top_n], 1):
                    st.subheader(f"Rank {i}: {result['resume_name']}")
                    display_results(result)
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
    if submit:
        if not jd.strip():
            st.error("Please provide a job description to analyze the resumes.")
        else:
            asyncio.run(analyze_resume_advanced())
