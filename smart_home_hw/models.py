"""Data models for the SmartHome homework assignment."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimeInterval:
    """Time interval with start and end in HH:MM format."""
    start: str  # "HH:MM"
    end: str    # "HH:MM"


@dataclass
class Preference:
    """Human preference constraint on device usage."""
    device_type: str
    room: str
    dislike_interval: TimeInterval
    reason: str


@dataclass
class ActionAffordance:
    """Action affordance with URI and parameter schema."""
    name: str
    uri: str
    input_schema: dict = field(default_factory=dict)


@dataclass
class PropertyAffordance:
    """Property affordance with URI for reading/writing."""
    name: str
    uri: str


@dataclass
class ArtifactInfo:
    """Information about a single artifact (device)."""
    name: str
    room: str
    artifact_uri: str
    device_type: str
    actions: list[ActionAffordance] = field(default_factory=list)
    properties: list[PropertyAffordance] = field(default_factory=list)


@dataclass
class ArtifactState:
    """Current state of an artifact (property values)."""
    artifact_uri: str
    properties: dict = field(default_factory=dict)  # {property_name: value}


@dataclass
class ActionOutput:
    """Expected or predicted output of a single action."""
    execution: str  # "success" or "error_input"
    affordance: Optional[str] = None  # action URI if success
    params: dict = field(default_factory=dict)  # action parameters if success
    test: dict = field(default_factory=dict)  # property verification if success


@dataclass
class Request:
    """A single smart home request."""
    id: str
    issued_at: str  # "HH:MM"
    input: str  # Natural language request
    output: list[ActionOutput] = field(default_factory=list)  # Ground truth
