"""Dependency resolver — maps upstream tool outputs to downstream tool inputs.

Attempts programmatic resolution first (zero LLM cost).
Falls back to cheap transformer LLM only when types are incompatible or
source field is absent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.models import ToolDependencyConfig
from llm.base import LLMAdapter, LLMCallRecord

logger = logging.getLogger(__name__)

# Mapping from JSON Schema type strings to Python types for type matching
_JSON_TO_PYTHON: Dict[str, tuple] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _is_simple_mapping(source_value: Any, target_type: str) -> bool:
    """Return True if the value can be passed programmatically without LLM help.

    Simple = same primitive type (str→str, int/float→number, bool→bool,
    list→array). dict→object is NOT simple (requires LLM to handle nested
    structure). Type mismatches are NOT simple.
    """
    if source_value is None:
        return False
    allowed_types = _JSON_TO_PYTHON.get(target_type)
    if allowed_types is None:
        return False
    # dict/object is never simple per spec
    if target_type == "object":
        return False
    return isinstance(source_value, allowed_types)


async def resolve(
    upstream_output: Dict[str, Any],
    dependency_config: ToolDependencyConfig,
    target_input_schema: Dict[str, Any],
    transformer_llm: LLMAdapter,
) -> Tuple[Dict[str, Any], bool, Optional[LLMCallRecord]]:
    """Resolve input parameters for a downstream tool from upstream output.

    Args:
        upstream_output: The dict returned by the upstream tool.
        dependency_config: The mapping config from agents.yaml.
        target_input_schema: JSON Schema of the downstream tool's input.
        transformer_llm: Cheap LLM for non-trivial transformations.

    Returns:
        Tuple of:
            resolved_params: dict to merge into downstream tool's input.
            used_llm: True if the transformer LLM was invoked.
            llm_record: LLMCallRecord if LLM was invoked, else None.
    """
    resolved: Dict[str, Any] = {}
    needs_llm = False
    properties = target_input_schema.get("properties", {})

    for mapping in dependency_config.mappings:
        source_value = upstream_output.get(mapping.source_field)

        if source_value is None:
            logger.debug(
                "Source field '%s' missing from upstream output → using LLM transformer",
                mapping.source_field,
            )
            needs_llm = True
            break

        target_field_schema = properties.get(mapping.target_field, {})
        target_type = target_field_schema.get("type", "string")

        if _is_simple_mapping(source_value, target_type):
            resolved[mapping.target_field] = source_value
            logger.debug(
                "Programmatic mapping: %s → %s (type=%s)",
                mapping.source_field,
                mapping.target_field,
                target_type,
            )
        else:
            logger.debug(
                "Non-simple mapping detected: %s (%s) → %s (%s) → using LLM transformer",
                mapping.source_field,
                type(source_value).__name__,
                mapping.target_field,
                target_type,
            )
            needs_llm = True
            break

    if not needs_llm:
        return resolved, False, None

    # LLM transformation path
    prompt = _build_transformation_prompt(
        upstream_output=upstream_output,
        target_input_schema=target_input_schema,
        dependency_config=dependency_config,
    )
    try:
        response = await transformer_llm.complete(
            messages=[{"role": "user", "content": prompt}],
            structured_output_schema=target_input_schema,
        )
        transformed = json.loads(response.content)
        from llm.base import LLMCallRecord as LLMRecord
        import time
        record = LLMRecord(
            role="transformer",
            provider="configured",
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            timestamp=time.time(),
        )
        return transformed, True, record
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Transformer LLM failed on first attempt: %s — retrying", e)
        # Retry once per spec
        try:
            response = await transformer_llm.complete(
                messages=[{"role": "user", "content": prompt}],
                structured_output_schema=target_input_schema,
            )
            transformed = json.loads(response.content)
            import time
            record = LLMCallRecord(
                role="transformer",
                provider="configured",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                timestamp=time.time(),
            )
            return transformed, True, record
        except Exception as e2:
            raise RuntimeError(
                f"Transformer LLM failed after retry: {e2}"
            ) from e2


def _build_transformation_prompt(
    upstream_output: Dict[str, Any],
    target_input_schema: Dict[str, Any],
    dependency_config: ToolDependencyConfig,
) -> str:
    mappings_desc = "; ".join(
        f"{m.source_field} → {m.target_field}"
        for m in dependency_config.mappings
    )
    return (
        "You are a data transformer. Given the output from an upstream tool and "
        "the required input schema for a downstream tool, produce a JSON object "
        "that satisfies the schema.\n\n"
        f"Upstream tool output:\n{json.dumps(upstream_output, indent=2)}\n\n"
        f"Target input schema:\n{json.dumps(target_input_schema, indent=2)}\n\n"
        f"Field mappings hint: {mappings_desc}\n\n"
        "Return ONLY a valid JSON object matching the target schema. No explanation."
    )
