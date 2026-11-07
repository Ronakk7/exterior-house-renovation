"""Strict parsing and validation of model-produced JSON envelopes."""

import json
from typing import Type

from pydantic import BaseModel, ValidationError


class InvalidModelJSON(ValueError):
    """The model response is not a valid JSON envelope for its schema."""


def parse_and_validate(raw_text: str, schema: Type[BaseModel]) -> BaseModel:
    """Parse JSON directly and reject undeclared top-level fields."""
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidModelJSON("Model response was not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise InvalidModelJSON("Model response must be a JSON object.")

    fields = getattr(schema, "model_fields", None)
    if fields is not None:
        extras = payload.keys() - fields.keys()
        if extras:
            raise InvalidModelJSON("Model response contained unknown top-level fields.")

    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise InvalidModelJSON("Model response did not match the required schema.") from exc
