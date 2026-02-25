"""
Domain models for the Lead Generation Pipeline.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Lead:
    """
    Represents a business lead discovered and qualified during a pipeline execution.
    This model acts as the core data transfer object (DTO) between the search,
    qualification, and outreach workers.

    Attributes:
        url (str): The source URL where the lead was found.
        company_name (Optional[str]): The identified name of the company.
        founder_name (Optional[str]): The name of the target contact or founder.
        email (Optional[str]): The direct email address for the contact.
        is_qualified (bool): Flag indicating if the lead passed strict LLM qualification.
        drafted_email (Optional[str]): A personalized outreach email drafted by the LLM.
        retry_count (int): Tracks the number of failed outreach delivery attempts.
    """
    url: str
    company_name: Optional[str] = None
    founder_name: Optional[str] = None
    email: Optional[str] = None
    is_qualified: bool = False
    drafted_email: Optional[str] = None
    retry_count: int = 0