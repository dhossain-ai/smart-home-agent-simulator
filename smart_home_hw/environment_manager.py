"""EnvironmentManager agent for providing environment information and preferences."""

import copy
import re
import threading
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from rdflib import Graph, Namespace, RDF, URIRef

from models import (
    ArtifactInfo,
    ArtifactState,
    ActionAffordance,
    PropertyAffordance,
    Preference,
)
from agent_protocol import AgentMailbox, MessageType, get_message_broker


TD = Namespace("https://www.w3.org/2019/wot/td#")
HMAS = Namespace("https://purl.org/hmas/")
HCTL = Namespace("https://www.w3.org/2019/wot/hypermedia#")
JSONSCHEMA = Namespace("https://www.w3.org/2019/wot/json-schema#")
EX = Namespace("http://example.org/")


class EnvironmentManagerAgent:
    """
    Agent responsible for providing environment information and active user preferences.

    This agent implements deterministic methods for accessing simulator state
    and preference constraints. All methods use HTTP queries and RDF parsing.
    """

    def __init__(
        self,
        simulator_base_url: str,
        preferences: list[Preference],
        timeout: int = 30,
        verbose: bool = False,
    ):
        self.simulator_url = simulator_base_url.rstrip("/")
        self.preferences = preferences
        self.timeout = timeout
        self.verbose = verbose

        # In-memory caches. Evaluation repeatedly queries the same homes, rooms,
        # artifacts, affordances, and states across strategies.
        self._rooms_cache: dict[str, list[str]] = {}
        self._artifacts_cache: dict[tuple[str, str], list[str]] = {}
        self._affordances_cache: dict[str, ArtifactInfo] = {}
        self._state_cache: dict[tuple[str, Optional[str]], ArtifactState] = {}
        self._preferences_cache: dict[str, list[Preference]] = {}

        self.mailbox = AgentMailbox("EnvironmentManager")
        get_message_broker().register_agent("EnvironmentManager", self.mailbox)
        self._running = False
        self._thread = None

    def start(self):
        """Start the agent message handler thread."""
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the agent message handler thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        """Main message handling loop."""
        while self._running:
            msg = self.mailbox.receive(timeout=1.0)
            if msg is None:
                continue

            if msg.message_type == MessageType.SHUTDOWN:
                break

            if msg.message_type == MessageType.REQUEST:
                self._handle_request(msg)

    def _handle_request(self, msg):
        """Handle incoming request message."""
        method = msg.method
        args = msg.args
        request_id = msg.request_id
        sender = msg.sender

        if self.verbose:
            print(f"[EnvironmentManager] ← Request from {sender}: {method}({args})")

        try:
            if method == "get_rooms":
                result = self.get_rooms(**args)
            elif method == "get_artifacts_in_room":
                result = self.get_artifacts_in_room(**args)
            elif method == "get_artifact_affordances":
                result = self.get_artifact_affordances(**args)
            elif method == "get_artifact_state":
                result = self.get_artifact_state(**args)
            elif method == "get_active_preferences":
                result = self.get_active_preferences(**args)
            elif method == "read_property":
                result = self.read_property(**args)
            else:
                raise ValueError(f"Unknown method: {method}")

            if self.verbose:
                print(f"[EnvironmentManager] → Response to {sender}: {method} = {result}")
            get_message_broker().route_response(request_id, result)

        except Exception as e:
            if self.verbose:
                print(f"[EnvironmentManager] ✗ Error handling {method}: {e}")
            get_message_broker().route_response(request_id, None, error=str(e))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _fetch_turtle(self, uri: str) -> str:
        """Fetch RDF/Turtle content from the simulator."""
        uri = self._strip_fragment(uri)
        response = requests.get(uri, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _parse_graph(self, turtle_text: str) -> Graph:
        """Parse Turtle RDF into an rdflib graph."""
        graph = Graph()
        graph.parse(data=turtle_text, format="turtle")
        return graph

    def _strip_fragment(self, uri: str) -> str:
        """Remove RDF fragment identifiers such as #artifact or #workspace."""
        return uri.split("#", 1)[0]

    def _uri_last_path_part(self, uri: str) -> str:
        """Return the final path component of a URI."""
        clean = self._strip_fragment(str(uri)).rstrip("/")
        return clean.rsplit("/", 1)[-1]

    def _room_from_artifact_uri(self, artifact_uri: str) -> str:
        """Extract room name from an artifact URI."""
        path = urlparse(self._strip_fragment(artifact_uri)).path
        parts = path.strip("/").split("/")

        # /workspaces/home12/guest_bedroom/artifacts/device
        if len(parts) >= 5 and parts[0] == "workspaces" and parts[3] == "artifacts":
            return parts[2]

        # /workspaces/home12/artifacts/device
        return "home"

    def _normalize_home_id(self, home_id: str) -> str:
        """Ensure home id uses simulator format, e.g. home12."""
        home_id = str(home_id)
        if home_id.startswith("home"):
            return home_id
        return f"home{home_id}"

    def _camel_to_snake(self, name: str) -> str:
        """Convert camelCase/PascalCase to snake_case."""
        name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        return name.lower()

    def _device_type_from_graph(self, graph: Graph, artifact_node: URIRef) -> str:
        """Extract device type from RDF type ex:DeviceType."""
        for type_uri in graph.objects(artifact_node, RDF.type):
            type_str = str(type_uri)
            if type_str.startswith(str(EX)):
                return self._camel_to_snake(type_str.replace(str(EX), ""))
        return ""

    def _schema_type(self, node, graph: Graph) -> str:
        """Convert JSON schema RDF type to a simple type string."""
        for schema_type in graph.objects(node, RDF.type):
            schema_type = str(schema_type)
            if "StringSchema" in schema_type:
                return "string"
            if "IntegerSchema" in schema_type:
                return "integer"
            if "NumberSchema" in schema_type:
                return "number"
            if "BooleanSchema" in schema_type:
                return "boolean"
            if "ArraySchema" in schema_type:
                return "array"
            if "ObjectSchema" in schema_type:
                return "object"
        return "unknown"

    def _parse_action_input_schema(self, graph: Graph, action_node) -> dict:
        """Parse WoT action input schema into a compact dict."""
        schema: dict[str, Any] = {}

        for input_schema in graph.objects(action_node, TD.hasInputSchema):
            for prop_node in graph.objects(input_schema, JSONSCHEMA.properties):
                param_name = None
                for name in graph.objects(prop_node, JSONSCHEMA.propertyName):
                    param_name = str(name).strip()
                    break

                if not param_name:
                    continue

                param_schema: dict[str, Any] = {
                    "type": self._schema_type(prop_node, graph)
                }

                enum_values = [str(v) for v in graph.objects(prop_node, JSONSCHEMA.enum)]
                if enum_values:
                    param_schema["enum"] = enum_values

                for min_value in graph.objects(prop_node, JSONSCHEMA.minimum):
                    try:
                        param_schema["minimum"] = int(str(min_value))
                    except ValueError:
                        param_schema["minimum"] = float(str(min_value))

                for max_value in graph.objects(prop_node, JSONSCHEMA.maximum):
                    try:
                        param_schema["maximum"] = int(str(max_value))
                    except ValueError:
                        param_schema["maximum"] = float(str(max_value))

                schema[param_name] = param_schema

        return schema

    def _extract_form_target(self, graph: Graph, affordance_node) -> Optional[str]:
        """Extract hctl:hasTarget URL from a TD affordance."""
        for form in graph.objects(affordance_node, TD.hasForm):
            for target in graph.objects(form, HCTL.hasTarget):
                return str(target)
        return None

    def _time_to_minutes(self, value: str) -> int:
        """Convert HH:MM to minutes after midnight."""
        hour, minute = value.strip().split(":")
        return int(hour) * 60 + int(minute)

    # -------------------------------------------------------------------------
    # Public API used by RequestSolver
    # -------------------------------------------------------------------------

    def read_property(self, property_uri: str) -> Any:
        """Read a property value from the simulator."""
        try:
            response = requests.get(property_uri, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def get_rooms(self, home_id: str) -> list[str]:
        """
        Return the list of room names for a given home.

        Example:
            get_rooms("home12") -> ["living_room", "guest_bedroom", ...]
        """
        home_id = self._normalize_home_id(home_id)

        if home_id in self._rooms_cache:
            return list(self._rooms_cache[home_id])

        home_uri = f"{self.simulator_url}/workspaces/{home_id}"

        try:
            graph = self._parse_graph(self._fetch_turtle(home_uri))
            rooms: list[str] = []

            for workspace in graph.subjects(RDF.type, HMAS.Workspace):
                for contained in graph.objects(workspace, HMAS.contains):
                    contained_uri = str(contained)

                    if not contained_uri.endswith("#workspace"):
                        continue

                    clean = self._strip_fragment(contained_uri)
                    parts = urlparse(clean).path.strip("/").split("/")

                    # /workspaces/home12/living_room
                    if len(parts) >= 3 and parts[0] == "workspaces" and parts[1] == home_id:
                        rooms.append(parts[2])

            result = sorted(set(rooms))
            self._rooms_cache[home_id] = result
            return list(result)

        except Exception as e:
            if self.verbose:
                print(f"[EnvironmentManager] Error in get_rooms({home_id}): {e}")
            return []

    def get_artifacts_in_room(self, home_id: str, room: str) -> list[str]:
        """
        Return the list of artifact URIs present in a given room.
        """
        home_id = self._normalize_home_id(home_id)
        cache_key = (home_id, room)

        if cache_key in self._artifacts_cache:
            return list(self._artifacts_cache[cache_key])

        if room == "home":
            room_uri = f"{self.simulator_url}/workspaces/{home_id}"
        else:
            room_uri = f"{self.simulator_url}/workspaces/{home_id}/{room}"

        try:
            graph = self._parse_graph(self._fetch_turtle(room_uri))
            artifacts: list[str] = []

            for workspace in graph.subjects(RDF.type, HMAS.Workspace):
                for contained in graph.objects(workspace, HMAS.contains):
                    contained_uri = str(contained)

                    if "/artifacts/" in contained_uri:
                        artifacts.append(self._strip_fragment(contained_uri))

            result = sorted(set(artifacts))
            self._artifacts_cache[cache_key] = result

            if self.verbose:
                print(
                    f"[EnvironmentManager] Found {len(result)} artifacts "
                    f"in {home_id}/{room}"
                )

            return list(result)

        except Exception as e:
            if self.verbose:
                print(f"[EnvironmentManager] Error in get_artifacts_in_room({home_id}, {room}): {e}")
            return []

    def get_artifact_affordances(self, artifact_uri: str) -> ArtifactInfo:
        """
        Return action and property affordances for a single artifact.
        """
        artifact_uri = self._strip_fragment(artifact_uri)

        if artifact_uri in self._affordances_cache:
            return copy.deepcopy(self._affordances_cache[artifact_uri])

        try:
            graph = self._parse_graph(self._fetch_turtle(artifact_uri))
            artifact_node = URIRef(f"{artifact_uri}#artifact")

            if (artifact_node, None, None) not in graph:
                # Fallback: find any artifact subject in the graph.
                for subject in graph.subjects(RDF.type, HMAS.Artifact):
                    artifact_node = subject
                    break

            artifact_name = self._uri_last_path_part(artifact_uri)
            room = self._room_from_artifact_uri(artifact_uri)
            device_type = self._device_type_from_graph(graph, artifact_node)

            actions: list[ActionAffordance] = []
            for action_node in graph.objects(artifact_node, TD.hasActionAffordance):
                target = self._extract_form_target(graph, action_node)
                if not target:
                    continue

                action_name = self._uri_last_path_part(target)
                input_schema = self._parse_action_input_schema(graph, action_node)

                actions.append(
                    ActionAffordance(
                        name=action_name,
                        uri=target,
                        input_schema=input_schema,
                    )
                )

            properties: list[PropertyAffordance] = []
            for prop_node in graph.objects(artifact_node, TD.hasPropertyAffordance):
                target = self._extract_form_target(graph, prop_node)
                if not target:
                    continue

                prop_name = self._uri_last_path_part(target)
                properties.append(PropertyAffordance(name=prop_name, uri=target))

            result = ArtifactInfo(
                name=artifact_name,
                room=room,
                artifact_uri=artifact_uri,
                device_type=device_type,
                actions=sorted(actions, key=lambda a: a.name),
                properties=sorted(properties, key=lambda p: p.name),
            )

            self._affordances_cache[artifact_uri] = copy.deepcopy(result)
            return result

        except Exception as e:
            if self.verbose:
                print(f"[EnvironmentManager] Error in get_artifact_affordances({artifact_uri}): {e}")

            result = ArtifactInfo(
                name=self._uri_last_path_part(artifact_uri),
                room=self._room_from_artifact_uri(artifact_uri),
                artifact_uri=artifact_uri,
                device_type="",
                actions=[],
                properties=[],
            )
            self._affordances_cache[artifact_uri] = copy.deepcopy(result)
            return result

    def get_artifact_state(
        self,
        artifact_uri: str,
        property_name: Optional[str] = None,
    ) -> ArtifactState:
        """
        Fetch current property values for an artifact from the simulator.

        Note:
            This caches read state information to speed up evaluation. Solver state
            reads occur before action execution, and the evaluator resets homes
            between tests, so this is appropriate for this workflow.
        """
        artifact_uri = self._strip_fragment(artifact_uri)
        cache_key = (artifact_uri, property_name)

        if cache_key in self._state_cache:
            return copy.deepcopy(self._state_cache[cache_key])

        state = ArtifactState(artifact_uri=artifact_uri, properties={})

        try:
            if property_name:
                property_uri = f"{artifact_uri}/properties/{property_name}"
                response = requests.get(property_uri, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                state.properties[property_name] = payload.get("value", payload)

                self._state_cache[cache_key] = copy.deepcopy(state)
                return state

            info = self.get_artifact_affordances(artifact_uri)
            for prop in info.properties:
                try:
                    response = requests.get(prop.uri, timeout=self.timeout)
                    response.raise_for_status()
                    payload = response.json()
                    state.properties[prop.name] = payload.get("value", payload)
                except Exception as e:
                    if self.verbose:
                        print(f"[EnvironmentManager] Could not read {prop.uri}: {e}")

            self._state_cache[cache_key] = copy.deepcopy(state)
            return state

        except Exception as e:
            if self.verbose:
                print(f"[EnvironmentManager] Error in get_artifact_state({artifact_uri}): {e}")
            self._state_cache[cache_key] = copy.deepcopy(state)
            return state

    def get_active_preferences(self, issued_at: str) -> list[Preference]:
        """
        Return preferences whose dislike interval contains the given time.

        Semantics:
            active when issued_at is inside [start, end)
        """
        if issued_at in self._preferences_cache:
            return list(self._preferences_cache[issued_at])

        try:
            issued_minutes = self._time_to_minutes(issued_at)
        except Exception:
            return []

        active: list[Preference] = []

        for pref in self.preferences:
            try:
                start = self._time_to_minutes(pref.dislike_interval.start)
                end = self._time_to_minutes(pref.dislike_interval.end)

                if start <= end:
                    is_active = start <= issued_minutes < end
                else:
                    # Handles intervals crossing midnight, e.g. 22:00 to 06:00.
                    is_active = issued_minutes >= start or issued_minutes < end

                if is_active:
                    active.append(pref)

            except Exception:
                continue

        self._preferences_cache[issued_at] = list(active)
        return list(active)