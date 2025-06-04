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
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="CV Ranker by Pakistan Recruitment")

def display_results(data):
    st.subheader("Analysis Results")
    
    if isinstance(data, dict): 
        st.metric("JD Match", data.get("##JD Match", "N/A"))
        
        if "Recruiter" in user_role:
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

if "user_role" not in st.session_state:
    st.title("CV Ranker")
    st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)
    st.header("Please select your role")
    user_role = st.selectbox("Are you a:", ["Job Seeker", "Recruiter"])
    if st.button("Continue"):
        st.session_state.user_role = user_role
else:
    user_role = st.session_state.user_role
    st.title("CV Ranker")
    st.markdown("**Powered by <a href='https://PakistanRecruitment.com' target='_blank'>PakistanRecruitment</a>**", unsafe_allow_html=True)
    st.header("Match a CV with any Job Post in seconds.", divider="grey")

    if user_role == "Job Seeker":
        st.markdown('''
            **How to use:**
            1. Upload your resume in PDF, MS Word (.doc, .docx) format.
            2. Paste the job description in the text area.
            3. Click Submit to analyze.
        ''')
        
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

        upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"], help="Please upload one or more PDF, MS Word (.doc, .docx) files", accept_multiple_files=False)
        jd = st.text_area("Paste job description", height=200)
        submit = st.button("Submit")

        async def analyze_resume_basic():
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
                    - Profile summary
                    Return ONLY valid JSON format: {"##JD Match": "X%", "##Profile Summary": "..."}
                    Keep response short and within 100 words.
                    """,
                    model=model,
                )

                if not upload_files or len([upload_files]) != 1:
                    st.error("Please upload exactly one resume")
                    return

                upload_file = upload_files
                st.subheader(f"Analysis for Resume: {upload_file.name}")
                text = input_text(upload_file)
                if not text:
                    return

                resume_input = f"Evaluate resume:\n{text}\n\nJob Description:\n{jd}"
                result = Runner.run_streamed(starting_agent=agent, input=resume_input)
                full_response = ""
                async for event in result.stream_events():
                    if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                        full_response += event.data.delta

                response_json = extract_json_from_response(full_response)
                if response_json:
                    display_results(response_json)
            except Exception as e:
                st.error(f"Server error: {str(e)}. Please try again later.")

        if submit:
            asyncio.run(analyze_resume_basic())

    elif user_role == "Recruiter":
        st.markdown('''
            **How to use:**
            1. Upload one or more resumes in PDF, MS Word (.doc, .docx) format.
            2. Paste the job description in the text area.
            3. Enter must-have and good-to-have keywords.
            4. Click Submit to analyze.
        ''')
        top_n = st.number_input("Select top N resumes to rank (e.g., 10, 20, 30)", min_value=1, max_value=100, value=10)
        must_have_keywords = st.text_area("Enter must-have keywords (comma-separated)", help="e.g., Python, SQL, 5 years")
        good_to_have_keywords = st.text_area("Enter good-to-have keywords (comma-separated)", help="e.g., JavaScript, Cloud")
        jd = st.text_area("Paste job description", height=200)
        upload_files = st.file_uploader("Upload your resume(s)", type=["pdf", "doc", "docx"], help="Please upload one or more PDF, MS Word (.doc, .docx) files", accept_multiple_files=True)
        submit = st.button("Submit")

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
            asyncio.run(analyze_resume_advanced())
