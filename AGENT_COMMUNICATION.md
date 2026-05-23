# Agent Communication Protocol

## Overview

Agents communicate via an asynchronous request-response protocol using message passing. Each agent runs in its own thread and processes incoming messages through a message broker.

## Architecture

### Components

1. **AgentMailbox** — Per-agent message queue and request/response handling
2. **MessageBroker** — Routes messages between agents
3. **Message** — Structured communication format with request/response types

### Message Types

- **REQUEST** — Agent A asks Agent B to perform a method
- **RESPONSE** — Agent B responds with result
- **ERROR** — Agent B responds with error
- **SHUTDOWN** — Signal to stop agent

## How It Works

### RequestSolver Requests Information

```python
# RequestSolver sends a request
result = self.mailbox.request(
    receiver="EnvironmentManager",
    method="get_artifacts_in_room",
    args={"home_id": "home12", "room": "guest_bedroom"},
    timeout=5.0
)
```

**Flow:**
1. RequestSolver creates a Message with REQUEST type
2. Message broker routes it to EnvironmentManager's mailbox
3. EnvironmentManager's thread receives the message
4. EnvironmentManager calls the method with the args
5. EnvironmentManager's thread sends a RESPONSE message
6. Message broker routes response back to RequestSolver
7. RequestSolver's mailbox delivers result, unblocking the request

### EnvironmentManager Handles Requests

```python
def _handle_request(self, msg):
    """Runs in EnvironmentManager's thread."""
    method = msg.method  # "get_artifacts_in_room"
    args = msg.args      # {"home_id": "home12", "room": "guest_bedroom"}
    
    # Call the corresponding method
    result = self.get_artifacts_in_room(**args)
    
    # Send response back
    get_message_broker().route_response(msg.request_id, result)
```

## DummyRequestSolver Demonstration

The DummyRequestSolver demonstrates the protocol by:

1. **Requesting artifacts** in guest_bedroom from home12
   ```
   [DummyRequestSolver] → Requesting artifacts in guest_bedroom
   [EnvironmentManager] ← Request from RequestSolver: get_artifacts_in_room(...)
   [EnvironmentManager] → Response to RequestSolver: get_artifacts_in_room = [...]
   [DummyRequestSolver] ← Received N artifact(s)
   ```

2. **Requesting affordances** for guestBedroomDehumidifiers
   ```
   [DummyRequestSolver] → Requesting affordances for guestBedroomDehumidifiers
   [EnvironmentManager] ← Request from RequestSolver: get_artifact_affordances(...)
   [EnvironmentManager] → Response to RequestSolver: get_artifact_affordances = {...}
   [DummyRequestSolver] ← Received affordance info
   ```

3. **Reading the property** value (mode)
   ```
   [DummyRequestSolver] → Reading property: mode
   [EnvironmentManager] ← Request from RequestSolver: read_property(...)
   [EnvironmentManager] → Response to RequestSolver: read_property = 'manual'
   [DummyRequestSolver] ← Current mode value: {'value': 'manual'}
   ```

4. **Returning the action**
   ```
   [DummyRequestSolver] → Returning hardcoded action
   ```

## Lifecycle

### Starting Agents

```python
env_manager = EnvironmentManagerAgent(simulator_url, preferences)
env_manager.start()  # Spawns message handler thread
```

### Agent Thread

```python
def _run(self):
    """Runs in dedicated thread."""
    while self._running:
        msg = self.mailbox.receive(timeout=1.0)
        if msg and msg.message_type == MessageType.REQUEST:
            self._handle_request(msg)
```

### Stopping Agents

```python
env_manager.stop()  # Signals shutdown and joins thread
```

## Request-Response Semantics

- **Timeout**: Default 5 seconds for requests
- **Blocking**: `mailbox.request()` blocks until response arrives
- **Errors**: Exceptions are caught and returned as ERROR messages
- **Threading**: Each agent has its own message handling thread

## Benefits

1. **Realistic Communication**: Agents communicate via message passing, not direct method calls
2. **Separation of Concerns**: Each agent is independent and runs concurrently
3. **Extensibility**: Easy to add new request types and agents
4. **Testing**: Can mock agents by injecting different implementations
5. **Observability**: All communication is logged and traceable

## Example: Adding a New Request Type

To add a new method:

1. **EnvironmentManager** implements the method:
   ```python
   def new_method(self, arg1: str) -> result:
       return result
   ```

2. **Update message handler** to recognize it:
   ```python
   elif msg.method == "new_method":
       result = self.new_method(**args)
   ```

3. **RequestSolver** calls it:
   ```python
   result = self.mailbox.request(
       "EnvironmentManager",
       "new_method",
       {"arg1": "value"},
       timeout=5.0
   )
   ```

