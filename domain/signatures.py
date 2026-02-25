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
        description="Exact email address found (e.g., info@, contact@). If found, decision MUST be CONVERT."
    )
    reason: str = Field(
        default="",
        description="States if this is a FULL-TIME or FREELANCE opportunity, and why it fits the candidate."
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
    <system>You are an expert AI Lead Generation Specialist and Technical Recruiter.</system>
    <instruction>
    Generate diverse DuckDuckGo search queries using Boolean logic (DO NOT use 'site:' operators).
    Your goal is a dual-track hunt:
    1. Find companies actively hiring full-time AI/Python engineers.
    2. Find early-stage startups that lack AI talent and need freelance/consulting expertise.
    Output queries that will uncover BOTH types of opportunities based on the <context>.
    </instruction>
    """
    cv_context: str = dspy.InputField(desc="The candidate's resume and background enclosed in <context> tags.")
    target_intent: str = dspy.InputField(
        desc="The specific types of companies or jobs we are hunting for enclosed in <context> tags.")

    output: SearchQueries = dspy.OutputField()


class EvaluateWebpageSignature(dspy.Signature):
    """
    <system>You are a ruthless Lead Qualification Engine and Data Extractor.</system>
    <instruction>
    Evaluate the provided scraped webpage to determine if this is a high-value opportunity for the candidate.
    An opportunity is valid if it is EITHER:
    A) A full-time job posting that matches the candidate's technical skills.
    B) A company/startup that currently needs AI/Python architecture and is a good candidate for a freelance pitch.

    CRITICAL EXTRACTION AND TEMPORAL RULES:
    1. Look deeply for ANY email addresses (e.g., info@, contact@, founders@, or personal names).
    2. If you find a valid email address AND the company is a match, you MUST set the decision to CONVERT immediately. Do not FOLLOW to read more about them.
    3. Only set the decision to FOLLOW if the company is a perfect match BUT you need to navigate to their 'Contact', 'About', or 'Team' page to find an email address.
    4. TEMPORAL CHECK: You must compare any dates, posting timestamps, or copyright years in the text against the provided `current_date`. If a job posting, article, or funding news is clearly older than 6 months from the `current_date`, it is STALE. You MUST set the decision to PRUNE.

    Output your logic and decision strictly based on the provided <document>.
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
    <system>You are an elite B2B Technical Sales Executive and Executive Candidate.</system>
    <instruction>
    Draft a concise, high-impact outreach email mapping the company's needs to the candidate's specific background.
    CRITICAL: You must adapt your tone based on the context.
    - If they are actively hiring for a role, position this as a direct application to the Hiring Manager.
    - If there is no job posting, position this as a high-value freelance/consulting pitch to the Founder.
    No fluff, no pleasantries outside the email body. Get straight to the technical value proposition.
    </instruction>
    """
    cv_context: str = dspy.InputField()
    founder_name: str = dspy.InputField(desc="The name of the target contact (Founder or Hiring Manager).")
    company_name: str = dspy.InputField()

    email_draft: str = dspy.OutputField(desc="The raw email text.")