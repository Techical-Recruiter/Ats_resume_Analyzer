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
        st.metric("JD Match", data.get("##JD Match", "N/A"))
        
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

if 'USERS' not in st.session_state:
    st.session_state.USERS = {"admin": {"password": "password123", "email": "admin@example.com", "plan": None}}

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
            st.rerun()

    with col2:
        st.subheader("Recruiter Free Plan")
        st.markdown("**Free with Restrictions**")
        st.markdown("- Analyze 10 Resumes for Free")
        st.markdown("- Upgrade for More Resumes")
        st.markdown("**Paid Upgrade: $50/month**")
        st.markdown("- Analyze 100 Resumes")
        if st.button("Upgrade to Basic", key="recruiter_basic_plan"):
            st.session_state.USERS[st.session_state.logged_in_user]["plan"] = "basic"
            st.session_state.user_role = "Recruiter"
            st.rerun()

    with col3:
        st.subheader("Recruiter Premium Plan")
        st.markdown("**$80/month**")
        st.markdown("- Analyze Unlimited Resumes")
        st.markdown("- Matching & Missing Keywords")
        st.markdown("- Priority Support")
        if st.button("Upgrade to Premium", key="recruiter_premium_plan"):
            st.session_state.USERS[st.session_state.logged_in_user]["plan"] = "premium"
            st.session_state.user_role = "Recruiter"
            st.rerun()

if "role_selected" not in st.session_state:
    st.title("CV Ranker")
    st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)
    st.header("Select Your Role")
    user_role = st.selectbox("Are you a:", ["Job Seeker", "Recruiter"])
    if st.button("Continue"):
        st.session_state.role_selected = True
        st.session_state.user_role = user_role
        if user_role == "Job Seeker":
            st.session_state.USERS["job_seeker_temp"] = {"password": None, "email": None, "plan": "free"}
            st.session_state.logged_in_user = "job_seeker_temp"
        st.rerun()
else:
    if st.session_state.user_role == "Job Seeker":
        logged_in_user = st.session_state.logged_in_user
        st.title("CV Ranker")
        st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)
        st.write("Welcome, Job Seeker!")

        st.header("Match your CV with any Job Post in seconds.", divider="grey")
        st.markdown('''
            **How to use:**
            1. Upload your resume in PDF, MS Word (.doc, .docx) format.
            2. Paste the job description in the text area.
            3. Click Submit to analyze.
        ''')

        upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"], help="Please upload one or more PDF, MS Word (.doc, .docx) files", accept_multiple_files=False)
        jd = st.text_area("Paste job description", height=200)
        submit = st.button("Submit")

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
                    You are a skilled ATS system. Analyze the resume against the job description and provide:
                    - Percentage match (e.g., "75%")
                    - Missing keywords
                    - Matching keywords (keywords from the job description that are present in the resume)
                    - Profile summary
                    Return ONLY valid JSON format: {"##JD Match": "X%", "##Missing Keywords": [], "##Matching Keywords": [], "##Profile Summary": "..."}
                    Keep response short and within 100 words.
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

                resume_input = f"Evaluate resume:\n{text}\n\nJob Description:\n{jd}"
                result = Runner.run_streamed(starting_agent=agent, input=resume_input)
                full_response = ""
                async for event in result.stream_events():
                    if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                        full_response += event.data.delta

                response_json = extract_json_from_response(full_response)
                if response_json:
                    display_results(response_json)
                    return True
                else:
                    return False
            except Exception as e:
                st.error(f"Server error: {str(e)}. Please try again later.")
                return False

        if submit:
            if not jd.strip(): 
                st.error("Please provide a job description to analyze the resume.")
            else:
                success = asyncio.run(analyze_resume_basic(upload_files, jd))

    else:
        if "logged_in_user" not in st.session_state:
            if "show_login" not in st.session_state:
                st.session_state.show_login = False

            st.title("CV Ranker Signup (Recruiter)")
            st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)

            if not st.session_state.show_login:
                username = st.text_input("Username")
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                if st.button("Sign Up"):
                    if username and email and password:
                        if username not in st.session_state.USERS:
                            st.session_state.USERS[username] = {"password": password, "email": email, "plan": "free_recruiter"}
                            st.session_state.show_login = True
                            st.success("Signup successful! Please log in.")
                            st.rerun()  
                        else:
                            st.error("Username already exists!")
                    else:
                        st.error("Please fill all fields!")
            else:
                st.title("CV Ranker Login (Recruiter)")
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                if st.button("Login"):
                    if username in st.session_state.USERS and st.session_state.USERS[username]["password"] == password:
                        st.session_state.logged_in_user = username
                        if f"{username}_recruiter_resumes_analyzed" not in st.session_state:
                            st.session_state[f"{username}_recruiter_resumes_analyzed"] = 0
                        if f"{username}_cooldown_end_time" not in st.session_state:
                            st.session_state[f"{username}_cooldown_end_time"] = None
                        st.rerun()
                    else:
                        st.error("Invalid username or password")

                st.button("Continue with Google", on_click=lambda: st.warning("Google login not implemented yet!"))
                st.button("Continue with GitHub", on_click=lambda: st.warning("GitHub login not implemented yet!"))
        else:
            logged_in_user = st.session_state.logged_in_user
            st.title("CV Ranker")
            st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)
            st.write(f"Welcome, {logged_in_user}!")

            # Pricing plans selection after login for Recruiter
            if st.session_state.USERS[logged_in_user]["plan"] is None:
                display_pricing_plans()
            else:
                plan = st.session_state.USERS[logged_in_user]["plan"]

                if plan in ["free_recruiter", "basic"] and f"{logged_in_user}_recruiter_resumes_analyzed" not in st.session_state:
                    st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] = 0
                elif plan == "premium" and f"{logged_in_user}_recruiter_resumes_analyzed" not in st.session_state:
                    st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] = 0

                limit = 10 if plan == "free_recruiter" else 100 if plan == "basic" else float('inf')
                if plan in ["free_recruiter", "basic"] and st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] >= limit:
                    st.warning(f"You have reached the {limit} resume limit on your current plan. Please upgrade to continue.")
                else:
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
                    upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"], help="Please upload one or more PDF, MS Word (.doc, .docx) files", accept_multiple_files=True)
                    submit = st.button("Submit")

                    async def analyze_resume_advanced():
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
                                You are a skilled ATS system. You are an experienced Resume analyzer who's has 40 years experience in every tech field. Use your experience and analyze the resume against the job description carefully and provide:
                                - Percentage match (e.g., "75%")
                                - Missing keywords
                                - Matching keywords (keywords from the job description that are present in the resume)
                                - Profile summary
                                Return ONLY valid JSON format: {"##JD Match": "X%", "##Missing Keywords": [], "##Matching Keywords": [], "##Profile Summary": "..."}
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
                            resume_count = len(upload_files)
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
                                                    results.append(response_json)
                                    except Exception as e:
                                        st.error(f"Error analyzing resume {idx}: {str(e)}. Skipping this resume.")

                            if not results:
                                st.error("No resumes matched the criteria. Please check keywords or upload different resumes.")
                            else:
                                if plan in ["free_recruiter", "basic"]:
                                    st.session_state[f"{logged_in_user}_recruiter_resumes_analyzed"] += resume_count
                                st.write(f"Total matched resumes: {len(results)}")
                                results.sort(key=lambda x: int(x["##JD Match"].replace("%", "")), reverse=True)
                                st.subheader(f"Top {top_n} Ranked Resumes")
                                for i, result in enumerate(results[:top_n], 1):
                                    st.subheader(f"Rank {i}: Resume {result['resume_index']} - {upload_files[result['resume_index'] - 1].name}")
                                    display_results(result)
                                if len(results) < top_n:
                                    st.warning(f"Only {len(results)} resumes matched the criteria, less than the requested top {top_n}.")

                        except Exception as e:
                            st.error(f"Server error: {str(e)}. Please try again later.")

                    if submit:
                        if not jd.strip():  
                            st.error("Please provide a job description to analyze the resumes.")
                        else:
                            asyncio.run(analyze_resume_advanced())
