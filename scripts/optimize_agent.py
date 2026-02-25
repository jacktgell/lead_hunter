"""
Optimization service for the Lead Hunter Agent.
Uses DSPy's BootstrapFewShotWithRandomSearch to compile high-performing prompts.
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Final

import dspy
from dspy.teleprompt import BootstrapFewShotWithRandomSearch

# Absolute path resolution for cross-platform stability
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from domain.signatures import EvaluateWebpageSignature
from core.config import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LeadHunter.Compiler")


class CompilerConstants:
    """Explicit constants for the optimization lifecycle."""
    CONFIG_FILE: Final[str] = "config.yaml"
    NUM_CANDIDATE_PROGRAMS: Final[int] = 4
    MAX_BOOTSTRAP_DEMOS: Final[int] = 3
    DEFAULT_PORT: Final[int] = 11434
    COMPILED_FILENAME: Final[str] = "compiled_agent.json"


class TrainingDataFactory:
    """
    Factory for generating dspy-compatible datasets.
    Designed to bridge raw JSON/YAML scenarios into labeled Examples.
    """

    @staticmethod
    def _get_gold_scenarios() -> List[dict]:
        """Returns the ground-truth scenarios used for agent alignment."""
        return [
            {
                "url": "https://tech-innovate.com/jobs",
                "text": "Founding AI Engineer needed. Skills: Python, GCP, LLMs. Posted: Feb 2026.",
                "decision": "CONVERT"
            },
            {
                "url": "https://deep-blue-sea.io/team",
                "text": "We are a stealth startup building vector databases. No active job posts.",
                "decision": "FOLLOW"
            },
            {
                "url": "https://spam-leads.net",
                "text": "Win a free iPhone by clicking here! Direct marketing opportunities.",
                "decision": "PRUNE"
            },
            {
                "url": "https://old-news.com/2022/article",
                "text": "AI is the future, says CEO in 2022 interview.",
                "decision": "PRUNE"
            }
        ]

    @classmethod
    def build_dataset(cls) -> List[dspy.Example]:
        """Constructs a strictly-typed dspy dataset."""
        scenarios = cls._get_gold_scenarios()
        current_date = datetime.now().strftime("%B %Y")

        # Contextual grounding for the optimizer
        cv_context = "Data Scientist/Engineer: Expert in Python, GCP, and LLM orchestration."
        intent = "Find high-growth AI startups and fractional consulting opportunities."

        return [
            dspy.Example(
                cv_context=cv_context,
                target_intent=intent,
                current_date=current_date,
                memory_buffer="INITIAL_QUERY",
                url=s["url"],
                page_text=s["text"],
                decision=s["decision"]
            ).with_inputs(
                'cv_context', 'target_intent', 'current_date',
                'memory_buffer', 'url', 'page_text'
            )
            for s in scenarios
        ]


def lead_evaluation_metric(example: dspy.Example, pred: dspy.Prediction, trace=None) -> bool:
    """
    Validation logic ensuring the agent's decision matches the gold standard.
    Supports both raw string and Pydantic object predictions.
    """
    try:
        # Extract prediction string from either attribute or nested evaluation object
        raw_pred = getattr(pred, 'evaluation', pred)
        actual = str(getattr(raw_pred, 'decision', raw_pred)).strip().upper()
        expected = str(example.decision).strip().upper()

        is_correct = actual == expected

        if trace is not None:
            logger.debug(f"Eval: Pred({actual}) vs Gold({expected}) | Result: {is_correct}")

        return is_correct
    except Exception as e:
        logger.error(f"Metric Error: {str(e)}")
        return False


class AgentCompiler:
    """
    Service responsible for compiling raw prompt signatures into optimized
    weights by bootstrapping few-shot demonstrations.
    """

    def __init__(self, config_path: str):
        self.settings = load_settings(config_path)
        self._initialize_backend()

    def _initialize_backend(self) -> None:
        """Configures the DSPy runtime with local inference parameters."""
        host_url = f"http://127.0.0.1:{self.settings.gcp.default_port}"

        lm = dspy.OllamaLocal(
            model=self.settings.llm.model_name,
            base_url=host_url,
            max_tokens=2048,
            temperature=0.0,  # Deterministic optimization
            timeout_s=300
        )
        dspy.settings.configure(lm=lm)
        logger.info(f"Compiler bound to Ollama: {self.settings.llm.model_name}")

    def run(self) -> None:
        """Executes the compilation pipeline."""
        logger.info("Starting Agent Optimization Sequence...")

        # 1. Data Splitting
        dataset = TrainingDataFactory.build_dataset()
        trainset = dataset[:3]  # Small set for bootstrapping
        # devset = dataset[3:] # Validation set

        # 2. Program Setup
        # TypedPredictor ensures the compiled output follows our Pydantic schema
        agent_program = dspy.TypedPredictor(EvaluateWebpageSignature)

        # 3. Optimizer Strategy
        optimizer = BootstrapFewShotWithRandomSearch(
            metric=lead_evaluation_metric,
            max_bootstrapped_demos=CompilerConstants.MAX_BOOTSTRAP_DEMOS,
            num_candidate_programs=CompilerConstants.NUM_CANDIDATE_PROGRAMS,
            trainset=trainset
        )

        # 4. Compilation Execution
        logger.info(f"Generating {CompilerConstants.NUM_CANDIDATE_PROGRAMS} program candidates...")
        compiled_program = optimizer.compile(agent_program, trainset=trainset)

        # 5. Serialization
        save_path = os.path.join(
            self.settings.app.active_workspace,
            CompilerConstants.COMPILED_FILENAME
        )
        compiled_program.save(save_path)

        logger.info(f"Compilation Successful. Weights persisted to: {save_path}")


if __name__ == "__main__":
    compiler = AgentCompiler(CompilerConstants.CONFIG_FILE)
    try:
        compiler.run()
    except KeyboardInterrupt:
        logger.warning("Optimization sequence interrupted by user.")
    except Exception as exc:
        logger.critical(f"Compiler crash: {exc}", exc_info=True)
        sys.exit(1)