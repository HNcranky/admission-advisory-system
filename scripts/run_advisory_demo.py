import argparse
import json
from typing import Any

from graph import graph
from state import AgentState


def _state_to_dict(result: Any) -> dict:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    return {"result": str(result)}


def run(query: str, admission_year: int = 2026, json_output: bool = False) -> int:
    initial_state = AgentState(user_query=query, admission_year=admission_year)
    result = graph.invoke(initial_state)
    state = _state_to_dict(result)

    if json_output:
        print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        return 0

    profile = state.get("student_profile", {})
    policy = state.get("policy_decision", {})
    recommendations = state.get("ranked_recommendations", [])

    print("=== Advisory Demo ===")
    print(f"Query: {query}")
    print(f"Admission Year: {state.get('admission_year', admission_year)}")
    print()
    print("Profile:")
    print(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
    print()
    print("Policy:")
    print(json.dumps(policy, ensure_ascii=False, indent=2, default=str))
    print()
    print(f"Recommendations: {len(recommendations)}")
    print("Final Answer:")
    print(state.get("final_answer") or state.get("advisory") or "(empty)")
    if state.get("uncertainty_reasons"):
        print("Uncertainty:")
        print(json.dumps(state["uncertainty_reasons"], ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run advisory graph with a custom query.")
    parser.add_argument(
        "--query",
        required=True,
        help="User query for advisory pipeline.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Admission year (default: 2026).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full state as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(query=args.query, admission_year=args.year, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
