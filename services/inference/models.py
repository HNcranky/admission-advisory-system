from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InferenceError(RuntimeError):
    """Raised when the inference provider hits a hard failure (network, auth, rate limit)."""


class InferenceRequest(BaseModel):
    agent_name: str
    task_type: str
    system_prompt: str
    user_prompt: str
    output_mode: str = "free_text"
    schema_name: Optional[str] = None
    temperature: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InferencePolicy(BaseModel):
    agent_name: str
    primary_model: str
    fallback_model: Optional[str] = None
    allow_fallback: bool = False
    output_mode: str = "free_text"
    max_retries: int = 1


class InferenceResult(BaseModel):
    agent_name: str
    model: str
    provider: str
    content: str
    parsed_data: Optional[Dict[str, Any]] = None
    failure_type: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    uncertainty_reasons: List[str] = Field(default_factory=list)