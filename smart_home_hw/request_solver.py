"""RequestSolver agent for handling smart home requests."""

import json
import re
import threading
from typing import Any, Optional

from models import Request, ActionOutput, ArtifactInfo
from environment_manager import EnvironmentManagerAgent
from agent_protocol import AgentMailbox, MessageType, get_message_broker

try:
    from llm_client import call_llm
except Exception:
    call_llm = None


DEVICE_ALIASES = {
    "light": ["light", "lights"],
    "air_conditioner": ["air conditioner", "ac", "air conditioning"],
    "heating": ["heating", "heater"],
    "fan": ["fan"],
    "blinds": ["blind", "blinds"],
    "curtain": ["curtain", "curtains"],
    "humidifier": ["humidifier"],
    "dehumidifier": ["dehumidifier", "dehumidifiers"],
    "air_purifier": ["air purifier"],
    "media_player": ["media player", "music player", "speaker"],
    "aromatherapy": ["aromatherapy", "aromatherapy device"],
    "water_heater": ["water heater"],
    "garage_door": ["garage door"],
    "vacuum_robot": ["vacuum robot", "vacuum"],
    "trash_pack": ["trash pack", "trash"],
}

ROOM_ALIASES = {
    "master_bedroom": ["master bedroom"],
    "guest_bedroom": ["guest bedroom"],
    "living_room": ["living room"],
    "dining_room": ["dining room"],
    "study_room": ["study room", "study"],
    "kitchen": ["kitchen"],
    "bathroom": ["bathroom"],
    "foyer": ["foyer"],
    "corridor": ["corridor", "hallway"],
    "balcony": ["balcony"],
    "garage": ["garage"],
    "store_room": ["store room", "storage room"],
    "home": ["home", "house"],
}

PROPERTY_ALIASES = {
    "brightness": ["brightness", "bright"],
    "color": ["color", "colour"],
    "state": ["state", "on", "off", "open", "close", "closed", "start", "stop"],
    "temperature": ["temperature", "degrees", "degree"],
    "mode": ["mode"],
    "fan_speed": ["fan speed"],
    "speed": ["speed"],
    "swing": ["swing"],
    "degree": ["degree", "percent", "percentage", "raise", "lower", "open", "close"],
    "intensity": ["intensity"],
    "interval": ["interval"],
    "volume": ["volume"],
    "artist": ["artist"],
}


class RequestSolverAgent:
    """
    Agent responsible for interpreting smart-home requests.

    Subclasses implement different reasoning strategies.
    """

    def __init__(
        self,
        env_manager: EnvironmentManagerAgent,
        llm_client,
    ):
        self.env_manager = env_manager
        self.llm_client = llm_client

    def solve(self, request: Request) -> list[ActionOutput]:
        raise NotImplementedError


class DummyRequestSolver(RequestSolverAgent):
    """Original dummy solver for testing the evaluation harness and agent communication."""

    def __init__(self, env_manager: EnvironmentManagerAgent, llm_client, verbose: bool = False):
        super().__init__(env_manager, llm_client)
        self.verbose = verbose
        self.mailbox = AgentMailbox("RequestSolver")
        get_message_broker().register_agent("RequestSolver", self.mailbox)

    def solve(self, request: Request) -> list[ActionOutput]:
        home_id = "home12"
        room = "guest_bedroom"
        artifact_name = "guestBedroomDehumidifiers"

        if self.verbose:
            print(f"\n[DummyRequestSolver] Processing request: {request.id}")

        try:
            self.mailbox.request(
                "EnvironmentManager",
                "get_artifacts_in_room",
                {"home_id": home_id, "room": room},
                timeout=5.0,
            )
        except Exception:
            pass

        artifact_uri = f"http://localhost:8080/workspaces/{home_id}/{room}/artifacts/{artifact_name}"

        try:
            self.mailbox.request(
                "EnvironmentManager",
                "get_artifact_affordances",
                {"artifact_uri": artifact_uri},
                timeout=5.0,
            )
        except Exception:
            pass

        return [
            ActionOutput(
                execution="success",
                affordance=f"{artifact_uri}/set_mode",
                params={"mode": "auto"},
            )
        ]


class BaseSmartHomeSolver(RequestSolverAgent):
    """Shared implementation utilities for all three strategies."""

    strategy_name = "base"

    def __init__(
        self,
        env_manager: EnvironmentManagerAgent,
        llm_client,
        verbose: bool = False,
    ):
        super().__init__(env_manager, llm_client)
        self.verbose = verbose

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def _home_id_from_request(self, request: Request) -> str:
        match = re.match(r"(home\d+)_", request.id)
        if match:
            return match.group(1)
        return request.id.split("_")[0]

    def _normalize(self, text: str) -> str:
        return re.sub(r"[^a-z0-9_ ]+", " ", str(text).lower()).strip()

    def _canonical_device_type(self, value: str) -> str:
        value = self._normalize(value).replace(" ", "_")
        for canonical, aliases in DEVICE_ALIASES.items():
            if value == canonical:
                return canonical
            if value in [a.replace(" ", "_") for a in aliases]:
                return canonical
        return value

    def _canonical_room(self, value: str) -> str:
        value_norm = self._normalize(value)
        value_snake = value_norm.replace(" ", "_")
        for canonical, aliases in ROOM_ALIASES.items():
            if value_snake == canonical:
                return canonical
            if value_norm in aliases:
                return canonical
        return value_snake

    def _device_matches(self, requested_type: str, artifact: ArtifactInfo) -> bool:
        requested = self._canonical_device_type(requested_type)
        actual = self._canonical_device_type(artifact.device_type)

        if requested == actual:
            return True

        name = self._normalize(artifact.name)
        aliases = DEVICE_ALIASES.get(requested, [requested])
        return any(alias in name.replace("_", " ") for alias in aliases)

    def _find_json_block(self, text: str) -> Any:
        """Extract JSON from LLM text."""
        if not text:
            raise ValueError("Empty LLM response")

        text = text.strip()

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON block found in LLM response")

        return json.loads(match.group(1))

    def _call_llm_json(self, prompt: str) -> Any:
        if self.llm_client is None or call_llm is None:
            raise RuntimeError("No LLM client available")

        response = call_llm(self.llm_client, prompt)
        return self._find_json_block(response)

    def _split_text_goals(self, request_text: str) -> list[str]:
        text = request_text.strip().rstrip(".")
        parts = re.split(r"\s+and\s+|,\s*then\s+|;\s*", text, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _extract_number(self, text: str) -> Optional[int | float]:
        match = re.search(r"(-?\d+(?:\.\d+)?)", text)
        if not match:
            return None

        raw = match.group(1)
        if "." in raw:
            return float(raw)
        return int(raw)

    def _infer_room_from_text(self, text: str, rooms: list[str]) -> Optional[str]:
        lower = text.lower()
        for room in rooms:
            labels = [room.replace("_", " ")] + ROOM_ALIASES.get(room, [])
            if any(label in lower for label in labels):
                return room
        return None

    def _infer_device_from_text(self, text: str) -> Optional[str]:
        lower = text.lower()
        for device_type, aliases in DEVICE_ALIASES.items():
            if any(alias in lower for alias in aliases):
                return device_type
        return None

    def _infer_property_from_text(self, text: str, device_type: Optional[str]) -> Optional[str]:
        lower = text.lower()

        if "turn on" in lower or "switch on" in lower:
            return "state"
        if "turn off" in lower or "switch off" in lower:
            return "state"
        if "open" in lower or "close" in lower or "raise" in lower or "lower" in lower:
            if device_type in ("curtain", "blinds", "garage_door"):
                return "degree" if device_type in ("curtain", "blinds") else "state"

        for prop, aliases in PROPERTY_ALIASES.items():
            if any(alias in lower for alias in aliases):
                return prop

        return None

    def _infer_action_value(self, text: str, property_name: Optional[str]) -> Any:
        lower = text.lower()
        number = self._extract_number(text)

        if property_name == "state":
            if "turn on" in lower or "switch on" in lower or "start" in lower or "play" in lower:
                return "on"
            if "turn off" in lower or "switch off" in lower or "stop" in lower:
                return "off"
            if "open" in lower:
                return "open"
            if "close" in lower:
                return "closed"

        if property_name == "mode":
            for mode in ["auto", "cool", "heat", "dry", "fan", "eco", "sleep"]:
                if re.search(rf"\b{mode}\b", lower):
                    return mode

        if property_name == "color":
            for color in ["red", "green", "blue", "yellow", "white", "warm", "cool"]:
                if re.search(rf"\b{color}\b", lower):
                    return color

        if property_name == "artist":
            match = re.search(r"artist\s+(?:to\s+)?([a-zA-Z0-9 _-]+)", text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return number

    def _is_adjust_request(self, text: str) -> bool:
        lower = text.lower()
        return any(word in lower for word in ["increase", "decrease", "raise", "lower", "reduce", "by"])

    def _adjust_sign(self, text: str) -> int:
        lower = text.lower()
        if any(word in lower for word in ["decrease", "lower", "reduce", "down"]):
            return -1
        return 1

    # ------------------------------------------------------------------
    # Environment discovery
    # ------------------------------------------------------------------

    def _collect_home_context(
        self,
        home_id: str,
        rooms: Optional[list[str]] = None,
        include_state: bool = True,
    ) -> list[dict]:
        if rooms is None:
            rooms = self.env_manager.get_rooms(home_id)

        context = []

        # Some homes may have home-level artifacts.
        candidate_rooms = list(dict.fromkeys(rooms + ["home"]))

        for room in candidate_rooms:
            artifact_uris = self.env_manager.get_artifacts_in_room(home_id, room)
            for artifact_uri in artifact_uris:
                info = self.env_manager.get_artifact_affordances(artifact_uri)
                state = self.env_manager.get_artifact_state(artifact_uri) if include_state else None

                context.append(
                    {
                        "room": info.room or room,
                        "artifact_uri": info.artifact_uri,
                        "name": info.name,
                        "device_type": info.device_type,
                        "actions": [
                            {
                                "name": action.name,
                                "uri": action.uri,
                                "input_schema": action.input_schema,
                            }
                            for action in info.actions
                        ],
                        "properties": [
                            {
                                "name": prop.name,
                                "uri": prop.uri,
                            }
                            for prop in info.properties
                        ],
                        "state": state.properties if state else {},
                        "_info": info,
                    }
                )

        return context

    def _find_artifact(
        self,
        context: list[dict],
        room: str,
        device_type: str,
    ) -> Optional[dict]:
        room = self._canonical_room(room)
        device_type = self._canonical_device_type(device_type)

        for item in context:
            info = item["_info"]
            if self._canonical_room(item["room"]) == room and self._device_matches(device_type, info):
                return item

        return None

    def _blocked_by_preference(
        self,
        request: Request,
        room: str,
        device_type: str,
    ) -> bool:
        active_preferences = self.env_manager.get_active_preferences(request.issued_at)

        room = self._canonical_room(room)
        device_type = self._canonical_device_type(device_type)

        for pref in active_preferences:
            pref_room = self._canonical_room(pref.room)
            pref_device = self._canonical_device_type(pref.device_type)
            if pref_room == room and pref_device == device_type:
                return True

        return False

    # ------------------------------------------------------------------
    # LLM/fallback parsing
    # ------------------------------------------------------------------

    def _parse_request_with_llm(
        self,
        request: Request,
        rooms: list[str],
        context: Optional[list[dict]] = None,
    ) -> list[dict]:
        context_text = ""

        if context is not None:
            small_context = []
            for item in context:
                small_context.append(
                    {
                        "room": item["room"],
                        "device_type": item["device_type"],
                        "artifact": item["name"],
                        "actions": [a["name"] for a in item["actions"]],
                        "properties": [p["name"] for p in item["properties"]],
                        "state": item.get("state", {}),
                    }
                )
            context_text = json.dumps(small_context, indent=2)

        prompt = f"""
You parse smart-home user requests into executable sub-goals.

Return ONLY valid JSON as a list. Do not include markdown.

Each list item must have:
- room: snake_case room name
- device_type: snake_case device type
- property: target property name
- value: target value for set_property, or numeric delta for adjust_property
- goal_type: "set_property" or "adjust_property"

Use these rooms:
{json.dumps(rooms)}

Request time: {request.issued_at}
Request text: {request.input}

Available context, if useful:
{context_text}

Examples:
"Set the light in the study room to 60%" ->
[{{"room":"study_room","device_type":"light","property":"brightness","value":60,"goal_type":"set_property"}}]

"Increase the air conditioner temperature in the bedroom by 2 degrees" ->
[{{"room":"bedroom","device_type":"air_conditioner","property":"temperature","value":2,"goal_type":"adjust_property"}}]

"Turn on the fan in the kitchen" ->
[{{"room":"kitchen","device_type":"fan","property":"state","value":"on","goal_type":"set_property"}}]
"""

        parsed = self._call_llm_json(prompt)
        if isinstance(parsed, dict):
            parsed = parsed.get("subgoals", [])
        if not isinstance(parsed, list):
            raise ValueError("LLM did not return a list")

        cleaned = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "room": self._canonical_room(item.get("room", "")),
                    "device_type": self._canonical_device_type(item.get("device_type", "")),
                    "property": item.get("property"),
                    "value": item.get("value"),
                    "goal_type": item.get("goal_type", "set_property"),
                }
            )
        return cleaned

    def _parse_request_fallback(self, request: Request, rooms: list[str]) -> list[dict]:
        goals = []

        for part in self._split_text_goals(request.input):
            room = self._infer_room_from_text(part, rooms)
            device_type = self._infer_device_from_text(part)
            prop = self._infer_property_from_text(part, device_type)
            value = self._infer_action_value(part, prop)
            goal_type = "adjust_property" if self._is_adjust_request(part) else "set_property"

            if room and device_type and prop:
                if goal_type == "adjust_property" and isinstance(value, (int, float)):
                    value = self._adjust_sign(part) * value

                goals.append(
                    {
                        "room": room,
                        "device_type": device_type,
                        "property": prop,
                        "value": value,
                        "goal_type": goal_type,
                    }
                )

        return goals

    def _parse_goals(
        self,
        request: Request,
        rooms: list[str],
        context: Optional[list[dict]] = None,
    ) -> list[dict]:
        try:
            return self._parse_request_with_llm(request, rooms, context)
        except Exception as e:
            if self.verbose:
                print(f"[{self.strategy_name}] LLM parsing failed; using fallback: {e}")
            return self._parse_request_fallback(request, rooms)

    # ------------------------------------------------------------------
    # Action mapping
    # ------------------------------------------------------------------

    def _action_name_for_goal(self, goal: dict, artifact: dict) -> Optional[str]:
        prop = goal.get("property")
        value = goal.get("value")
        device_type = self._canonical_device_type(goal.get("device_type", ""))

        if prop == "state":
            if value == "on":
                preferred = ["turn_on", "start", "play", "open"]
            elif value in ("off", "closed"):
                preferred = ["turn_off", "stop", "close"]
            elif value == "open":
                preferred = ["open"]
            else:
                preferred = ["turn_off", "stop"]
        elif prop == "temperature":
            preferred = ["set_temperature"]
        elif prop == "brightness":
            preferred = ["set_brightness"]
        elif prop == "color":
            preferred = ["set_color"]
        elif prop == "mode":
            preferred = ["set_mode"]
        elif prop in ("fan_speed", "speed"):
            preferred = ["set_fan_speed", "set_speed"]
        elif prop == "swing":
            preferred = ["set_swing"]
        elif prop == "degree":
            if value == "open":
                preferred = ["open"]
            elif value in ("closed", "close"):
                preferred = ["close"]
            else:
                preferred = ["set_degree"]
        elif prop == "intensity":
            preferred = ["set_intensity"]
        elif prop == "interval":
            preferred = ["set_interval"]
        elif prop == "volume":
            preferred = ["set_volume"]
        elif prop == "artist":
            preferred = ["set_artist"]
        else:
            preferred = [f"set_{prop}"] if prop else []

        action_names = [a["name"] for a in artifact["actions"]]

        for name in preferred:
            if name in action_names:
                return name

        # Fallback: any set_<property> action.
        if prop:
            fallback = f"set_{prop}"
            if fallback in action_names:
                return fallback

        return None

    def _params_for_action(
        self,
        goal: dict,
        action_name: str,
        artifact: dict,
    ) -> dict:
        prop = goal.get("property")
        value = goal.get("value")

        if action_name in ("turn_on", "turn_off", "open", "close", "start", "stop", "play", "pause"):
            return {}

        # For set_degree, natural-language "open/close" can map to numeric values.
        if action_name == "set_degree":
            if value == "open":
                value = 100
            elif value in ("closed", "close"):
                value = 0

        # Use schema parameter name when available.
        action = next((a for a in artifact["actions"] if a["name"] == action_name), None)
        if action:
            schema = action.get("input_schema") or {}
            if len(schema) == 1:
                param_name = next(iter(schema.keys()))
                return {param_name: value}

        if action_name.startswith("set_"):
            return {action_name.replace("set_", ""): value}

        if prop:
            return {prop: value}

        return {}

    def _compute_adjusted_value(self, goal: dict, artifact: dict) -> Any:
        prop = goal.get("property")
        delta = goal.get("value")

        try:
            delta = float(delta)
            if delta.is_integer():
                delta = int(delta)
        except Exception:
            return delta

        current = artifact.get("state", {}).get(prop)

        if current is None:
            state = self.env_manager.get_artifact_state(artifact["artifact_uri"], prop)
            current = state.properties.get(prop)

        try:
            new_value = current + delta
        except Exception:
            return delta

        # Keep typical percentage properties inside [0, 100].
        if prop in ("brightness", "degree", "intensity", "volume", "speed", "fan_speed"):
            new_value = max(0, min(100, new_value))

        if isinstance(new_value, float) and new_value.is_integer():
            return int(new_value)
        return new_value

    def _goal_to_action_output(
        self,
        request: Request,
        goal: dict,
        context: list[dict],
    ) -> ActionOutput:
        room = goal.get("room")
        device_type = goal.get("device_type")

        if not room or not device_type:
            return ActionOutput(execution="error_input")

        if self._blocked_by_preference(request, room, device_type):
            return ActionOutput(execution="error_input")

        artifact = self._find_artifact(context, room, device_type)
        if artifact is None:
            return ActionOutput(execution="error_input")

        if goal.get("goal_type") == "adjust_property":
            goal = dict(goal)
            goal["value"] = self._compute_adjusted_value(goal, artifact)

        action_name = self._action_name_for_goal(goal, artifact)
        if not action_name:
            return ActionOutput(execution="error_input")

        action = next((a for a in artifact["actions"] if a["name"] == action_name), None)
        if not action:
            return ActionOutput(execution="error_input")

        params = self._params_for_action(goal, action_name, artifact)

        return ActionOutput(
            execution="success",
            affordance=action["uri"],
            params=params,
        )

    def _solve_from_context(
        self,
        request: Request,
        rooms: list[str],
        context: list[dict],
    ) -> list[ActionOutput]:
        goals = self._parse_goals(request, rooms, context)

        if self.verbose:
            print(f"[{self.strategy_name}] Parsed goals: {json.dumps(goals, indent=2)}")

        outputs = [self._goal_to_action_output(request, goal, context) for goal in goals]

        if not outputs:
            return [ActionOutput(execution="error_input")]

        return outputs


class FullContextSolver(BaseSmartHomeSolver):
    """
    Strategy 1: Full Context.

    Fetches all environment information first, then asks the LLM to parse the request
    with the complete home context available.
    """

    strategy_name = "full_context"

    def solve(self, request: Request) -> list[ActionOutput]:
        home_id = self._home_id_from_request(request)
        rooms = self.env_manager.get_rooms(home_id)
        context = self._collect_home_context(home_id, rooms=rooms, include_state=True)
        return self._solve_from_context(request, rooms, context)


class SequentialSolver(BaseSmartHomeSolver):
    """
    Strategy 2: Sequential Affordance Exploration.

    First identifies likely rooms/devices, then queries only relevant rooms.
    """

    strategy_name = "sequential"

    def solve(self, request: Request) -> list[ActionOutput]:
        home_id = self._home_id_from_request(request)
        rooms = self.env_manager.get_rooms(home_id)

        rough_goals = self._parse_request_fallback(request, rooms)

        if not rough_goals:
            try:
                rough_goals = self._parse_request_with_llm(request, rooms, context=None)
            except Exception:
                rough_goals = []

        relevant_rooms = sorted(
            set(goal["room"] for goal in rough_goals if goal.get("room"))
        )

        if not relevant_rooms:
            relevant_rooms = rooms

        context = self._collect_home_context(home_id, rooms=relevant_rooms, include_state=True)

        # Parse again with the discovered context.
        return self._solve_from_context(request, rooms, context)


class SemanticSolver(BaseSmartHomeSolver):
    """
    Strategy 3: Semantic Classification + Deterministic Mapping.

    Classifies each sub-goal into set_property or adjust_property, then uses code to
    map the sub-goal to simulator affordances and parameters.
    """

    strategy_name = "semantic"

    def solve(self, request: Request) -> list[ActionOutput]:
        home_id = self._home_id_from_request(request)
        rooms = self.env_manager.get_rooms(home_id)

        goals = self._parse_goals(request, rooms, context=None)

        relevant_rooms = sorted(
            set(goal["room"] for goal in goals if goal.get("room"))
        )

        if not relevant_rooms:
            relevant_rooms = rooms

        context = self._collect_home_context(home_id, rooms=relevant_rooms, include_state=True)

        outputs = [self._goal_to_action_output(request, goal, context) for goal in goals]

        if not outputs:
            return [ActionOutput(execution="error_input")]

        return outputs