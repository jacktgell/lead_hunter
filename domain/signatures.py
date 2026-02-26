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
    - 30% Multiplier Search: Target Tech Recruitment Agencies + AI.
    - 40% Broad Tech Search: Target established tech companies, startups, and software agencies.
    - 30% Job Search: Target general hiring intent for Python/Data/AI.

    ANCHORING: Every single query MUST include one of the specific geographic locations provided in the target_intent.
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
    We are casting a WIDE NET. Jack is open to Full-Time roles, Contract work, Freelance projects, or Agency representation.

    EXPANSION RULES (DO NOT PRUNE):
    - DO NOT PRUNE staffing firms, tech recruiters, or software agencies. They are highly valuable force multipliers.
    - DO NOT PRUNE established tech companies or startups just because they don't have an active job posting right now. If they have an established AI/Python workforce, they are a valid networking target.

    NAVIGATION STRATEGY (STOP HALLUCINATING URLS):
    1. If you are on a Job Board or LinkedIn profile and identify a tech company:
       - DO NOT guess their sub-pages (e.g. don't guess /careers).
       - Instead, set decision to FOLLOW and provide the ROOT DOMAIN (e.g. https://company.com).
    2. If you are already on the company's website:
       - ONLY FOLLOW links that are actually visible in the provided content.

    EXTRACTION & CONVERSION (STRICT EMAIL RULE):
    1. YOU MUST HAVE AN EMAIL TO CONVERT. If you find a human email (Founder, HR, CTO) or generic email (careers@, info@) AND the company is a match, set decision to CONVERT.
    2. If the company is a match but NO EMAIL is visible on the current page, set decision to FOLLOW and extract target URLs like /contact, /about, /team, or /careers to hunt for the email.
    3. PRUNE ONLY non-business noise (Tutorials, Forums, Personal blogs).
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