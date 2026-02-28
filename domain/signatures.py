"""
Data contracts and DSPy Signatures for LLM interactions.
Defines strict inputs, outputs, and prompts for the autonomous lead hunter.
"""

import dspy
from pydantic import BaseModel, Field
from typing import List, Optional, Literal


# --- Pydantic Output Models (Strict JSON Validation) ---

class WebpageEvaluation(BaseModel):
    """Structured output for the LLM webpage evaluation task."""

    decision: Literal["CONVERT", "FOLLOW", "PRUNE"] = Field(
        description="Must be exactly one of: CONVERT, FOLLOW, or PRUNE."
    )
    discovery_summary: str = Field(
        description="Brief, logical reasoning for the decision based on the text."
    )
    next_target_urls: List[str] = Field(
        default_factory=list,
        description="List of specific internal URLs to explore if decision is FOLLOW."
    )
    company: str = Field(
        default="Unknown",
        description="Extracted name of the company."
    )
    person: str = Field(
        default="Unknown",
        description="Extracted name of the founder or hiring manager."
    )
    email: Optional[str] = Field(
        default=None,
        description="Exact email address found. If NO email is found, output null/None. Do NOT hallucinate."
    )
    reason: str = Field(
        default="",
        description="States if this is a FULL-TIME, FREELANCE, or AGENCY PARTNERSHIP opportunity."
    )


class SearchQueries(BaseModel):
    """Structured output for query generation."""

    queries: List[str] = Field(
        description="List of 5 to 10 boolean DuckDuckGo search queries."
    )


# --- DSPy Signatures (Input -> Output Contracts) ---
# Note: Docstrings here are passed directly to the LLM. Do not add standard code comments inside them.

class GenerateSearchQueriesSignature(dspy.Signature):
    """
    <system>You are an expert OSINT Hunter and Tech Recruiter.</system>
    <instruction>
    Generate 10 diverse DuckDuckGo search queries using Boolean logic.
    STRATEGY:
    - 40% Pure Software/SaaS Companies: Queries targeting "software company", "SaaS startup", "AI product firm".
    - 30% Tech Recruiters: Queries targeting "IT recruitment agency", "tech headhunter", "software engineering staffing".
    - 30% Tech Consultancies: Queries targeting "software development agency", "digital transformation consultancy".

    ANCHORING: Every single query MUST include one of the specific geographic locations provided in the target_intent.
    ANTI-PATTERN: Do NOT use generic job search terms like "jobs", "hiring", or "salary" to avoid job boards. Use business discovery terms like "about us", "our services", or "our clients".
    </instruction>
    """
    cv_context: str = dspy.InputField(desc="The candidate's resume and background enclosed in <context> tags.")
    target_intent: str = dspy.InputField(
        desc="The specific types of companies or jobs we are hunting for enclosed in <context> tags. This contains the required geographic locations.")

    output: SearchQueries = dspy.OutputField()


class EvaluateWebpageSignature(dspy.Signature):
    """
    <system>You are a highly adaptable AI/Tech Recruitment Matchmaker.</system>
    <instruction>
    Evaluate the webpage to identify if this company is a match for Jack Gell.

    EXPANSION RULES (STRICT FILTERING):
    - ONLY set decision to FOLLOW or CONVERT if the company's core business is selling software, tech consulting, or IT recruitment.
    - PRUNE non-tech companies (e.g., a hospital, a retail brand, a real estate firm) even if they mention Python or AI.
    - PRUNE all job boards, salary aggregators, and tech news articles.

    NAVIGATION STRATEGY:
    1. If you are on a Tech Company or IT Recruiter website:
       - ONLY FOLLOW links that are actually visible in the provided content to find an email (e.g., /contact, /about, /team).
    2. YOU MUST HAVE AN EMAIL TO CONVERT. If you find a human email (Founder, HR, CTO) or generic email (careers@, info@) AND the company is a match, set decision to CONVERT.
    </instruction>
    """

    cv_context: str = dspy.InputField()
    target_intent: str = dspy.InputField()
    current_date: str = dspy.InputField(desc="The current actual month and year.")
    memory_buffer: str = dspy.InputField(desc="Previous links clicked to get here enclosed in <scratchpad> tags.")
    url: str = dspy.InputField()
    page_text: str = dspy.InputField(desc="Raw text extracted from the webpage enclosed in <document> tags.")

    evaluation: WebpageEvaluation = dspy.OutputField()


class DraftOutreachSignature(dspy.Signature):
    """
    <system>You are a highly capable, pragmatic AI/Python Software Engineer reaching out for opportunities.</system>
    <instruction>
    Draft a concise, professional outreach email mapping the company's domain to the candidate's background.
    CRITICAL: Jack is highly flexible and looking for the right team or project.
    - Tone: Confident, approachable, and eager to contribute. Do NOT sound like an aggressive salesman.
    - If they are actively hiring: Position as a direct, strong candidate for the team.
    - If they are an agency/recruiter: Position as a versatile asset available for their clients (contract or full-time).
    - If there is no job posting: Send a brief networking inquiry asking if they use external contractors or are planning to expand their Python/Data team soon.
    Get straight to the point without fluffy pleasantries.
    </instruction>
    """
    cv_context: str = dspy.InputField()
    founder_name: str = dspy.InputField(desc="The name of the target contact (Founder, HR, or Hiring Manager).")
    company_name: str = dspy.InputField()

    email_draft: str = dspy.OutputField(desc="The raw email text.")