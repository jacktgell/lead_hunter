import os
import yaml
from datetime import datetime
from typing import List, Dict, Any

import dspy

from core.interfaces import ILLMProvider
from core.config import LlmConfig
from domain.models import Lead
from domain.signatures import (
    GenerateSearchQueriesSignature,
    EvaluateWebpageSignature,
    DraftOutreachSignature,
    WebpageEvaluation
)
from core.logger import get_logger

logger = get_logger(__name__)


class DspyOllamaLLM(ILLMProvider):
    """
    DSPy implementation of the LLM Provider.
    Handles semantic routing, structured output enforcement, and zero-shot fallback.
    """

    def __init__(self, host_url: str, config: LlmConfig):
        self.config = config
        self.cv_context: str = ""
        self.target_intent: str = ""

        self._load_cv_context()
        self._initialize_dspy_lm(host_url)

        # Initialize DSPy Predictors (DSPy 2.5+ Native Pydantic Support)
        self.query_generator = dspy.Predict(GenerateSearchQueriesSignature)
        self.page_evaluator = dspy.Predict(EvaluateWebpageSignature)
        self.outreach_drafter = dspy.Predict(DraftOutreachSignature)

        self._load_optimizer_weights()

    def _initialize_dspy_lm(self, host_url: str) -> None:
        """Configures the global DSPy LM instance via LiteLLM routing."""
        logger.info(f"Binding DSPy to Engine: {self.config.model_name} at {host_url}")

        self.lm = dspy.LM(
            model=f"ollama_chat/{self.config.model_name}",
            api_base=host_url,
            api_key="ollama_local",  # Required dummy key for LiteLLM
            max_tokens=8192,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            timeout=120.0,
            num_ctx=self.config.num_ctx,
            seed=self.config.seed,
            repeat_penalty=self.config.repeat_penalty
        )
        dspy.settings.configure(lm=self.lm)

    def _load_optimizer_weights(self) -> None:
        """Attempts to load mathematically optimized prompt weights if available."""
        compiled_path = os.path.join(os.path.dirname(self.config.prompts_path), "compiled_agent.json")
        if os.path.exists(compiled_path):
            logger.info("DSPy: Loading compiled prompt weights.")
            try:
                self.page_evaluator.load(compiled_path)
            except Exception as e:
                logger.error(f"Failed to load compiled weights, falling back to Zero-Shot: {str(e)}")
        else:
            logger.warning("DSPy: No compiled weights found. Running in Zero-Shot base mode.")

    def _load_cv_context(self) -> None:
        """Loads and pre-wraps the candidate profile in strict XML tags for LLM grounding."""
        if not os.path.exists(self.config.prompts_path):
            raise FileNotFoundError(f"Missing config file at {self.config.prompts_path}")

        try:
            with open(self.config.prompts_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            raw_cv = yaml.dump(data.get('candidate_profile', {}))
            raw_intent = data.get('config', {}).get('target_intent', 'Find high value AI clients.')

            # Pre-compute XML wrapping to save runtime string concatenation overhead
            self.cv_context = f"<context>\n{raw_cv}\n</context>"
            self.target_intent = f"<context>\n{raw_intent}\n</context>"
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse prompt configuration YAML: {str(e)}")

    def _log_last_interaction(self, context_name: str) -> None:
        """Extracts and logs the raw prompt and response from the DSPy history buffer."""
        if not self.lm.history:
            return

        try:
            last_record = self.lm.history[-1]
            prompt = last_record.get('prompt', last_record.get('messages', 'No prompt recorded'))
            raw_response = last_record.get('response', 'No response recorded')

            # Defensive extraction of LiteLLM response objects
            response_text = str(raw_response)
            if hasattr(raw_response, 'choices') and raw_response.choices:
                response_text = raw_response.choices[0].message.content
            elif isinstance(raw_response, dict) and 'choices' in raw_response:
                response_text = raw_response['choices'][0]['message']['content']

            logger.debug(
                f"\n{'=' * 60}\n"
                f"LLM TRACE: {context_name}\n"
                f"{'=' * 60}\n"
                f"--- RAW PROMPT ---\n{prompt}\n\n"
                f"--- RAW RESPONSE ---\n{response_text}\n"
                f"{'=' * 60}"
            )
        except Exception as e:
            logger.debug(f"Could not extract LLM history trace: {str(e)}")

    def generate_search_queries(self, persona_prompt: str) -> List[str]:
        logger.info("DSPy: Generating boolean search queries...")
        try:
            tagged_intent = f"<context>\n{persona_prompt}\n</context>"
            result = self.query_generator(
                cv_context=self.cv_context,
                target_intent=tagged_intent
            )
            self._log_last_interaction("Search Query Generation")
            return result.output.queries

        except Exception as e:
            logger.error(f"Query Generation failed. Falling back to default query. Error: {str(e)}")
            # Fallback constraint: Never crash the pipeline if query generation fails
            return ['"seed stage" AND "AI startup"']

    def investigate_page(self, page_text: str, url: str, memory_buffer: str) -> Dict[str, Any]:
        logger.debug(f"DSPy: Evaluating webpage: {url}\n--- MEMORY ---\n{memory_buffer.strip()}\n--------------")

        try:
            tagged_page_text = f"<document>\n{page_text}\n</document>"
            tagged_memory = f"<scratchpad>\n{memory_buffer}\n</scratchpad>"

            result = self.page_evaluator(
                cv_context=self.cv_context,
                target_intent=self.target_intent,
                current_date=datetime.now().strftime("%B %Y"),
                memory_buffer=tagged_memory,
                url=url,
                page_text=tagged_page_text
            )

            self._log_last_interaction(f"Webpage Evaluation: {url}")
            eval_data: WebpageEvaluation = result.evaluation

            logger.info(
                f"\n+--- AI DECISION {'-' * 45}+\n"
                f"| TARGET:    {url}\n"
                f"| COMPANY:   {eval_data.company}\n"
                f"| DECISION:  {eval_data.decision}\n"
                f"| REASONING: {eval_data.discovery_summary}\n"
                f"+{'-' * 60}+"
            )

            # Map the Pydantic schema to the expected pipeline dictionary contract
            return {
                "decision": eval_data.decision,
                "discovery_summary": eval_data.discovery_summary,
                "next_target_urls": eval_data.next_target_urls,
                "lead_data": {
                    "company": eval_data.company,
                    "person": eval_data.person,
                    "email": eval_data.email,
                    "reason": eval_data.reason
                }
            }

        except Exception as e:
            logger.error(f"Webpage Evaluation failed for {url}: {str(e)}", exc_info=True)
            return {
                "decision": "PRUNE",
                "discovery_summary": f"Execution Error: {str(e)}",
                "lead_data": {}
            }

    def draft_outreach(self, lead: Lead) -> str:
        logger.debug(f"DSPy: Drafting outreach for {lead.company_name}")
        try:
            result = self.outreach_drafter(
                cv_context=self.cv_context,
                founder_name=lead.founder_name or "Founder",
                company_name=lead.company_name or "your company"
            )
            self._log_last_interaction(f"Draft Outreach: {lead.company_name}")
            return result.email_draft
        except Exception as e:
            logger.error(f"Failed to draft outreach for {lead.company_name}: {str(e)}", exc_info=True)
            return ""