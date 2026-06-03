from typing import Dict

from pydantic import BaseModel, Field

from services.inference.models import InferencePolicy


class ModelRegistry(BaseModel):
    default_model: str
    agent_overrides: Dict[str, Dict[str, object]] = Field(default_factory=dict)

    def resolve(self, agent_name: str) -> InferencePolicy:
        override = self.agent_overrides.get(agent_name, {})
        return InferencePolicy(
            agent_name=agent_name,
            primary_model=str(override.get("primary_model", self.default_model)),
            fallback_model=override.get("fallback_model"),
            allow_fallback=bool(override.get("allow_fallback", False)),
            output_mode=str(override.get("output_mode", "free_text")),
            max_retries=int(override.get("max_retries", 1)),
        )