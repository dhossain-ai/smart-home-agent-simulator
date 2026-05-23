"""Agent communication protocol with request-response interaction."""

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import queue
import threading
import time
import uuid


class MessageType(Enum):
    """Types of messages agents can send."""
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    SHUTDOWN = "shutdown"


@dataclass
class Message:
    """A message in the agent communication protocol."""
    message_type: MessageType
    sender: str  # Agent ID
    receiver: str  # Agent ID
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    method: Optional[str] = None  # Method name for requests
    args: dict = field(default_factory=dict)  # Method arguments
    result: Any = None  # Response data
    error: Optional[str] = None  # Error message


class AgentMailbox:
    """Mailbox for agent message passing."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._inbox = queue.Queue()
        self._pending_responses = {}  # request_id -> Event
        self._response_results = {}  # request_id -> result

    def send(self, message: Message):
        """Queue an incoming message."""
        self._inbox.put(message)

    def receive(self, timeout: float = 5.0) -> Optional[Message]:
        """Receive next message with timeout."""
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def request(self, receiver: str, method: str, args: dict, timeout: float = 5.0) -> Any:
        """Send a request and wait for response."""
        request_id = str(uuid.uuid4())
        msg = Message(
            message_type=MessageType.REQUEST,
            sender=self.agent_id,
            receiver=receiver,
            request_id=request_id,
            method=method,
            args=args,
        )

        event = threading.Event()
        self._pending_responses[request_id] = event

        # Send request (will be routed by message broker)
        _message_broker.route(msg)

        # Wait for response
        if event.wait(timeout=timeout):
            result = self._response_results.pop(request_id, None)
            return result
        else:
            raise TimeoutError(f"No response to request {request_id} within {timeout}s")

    def respond(self, request_id: str, result: Any, error: Optional[str] = None):
        """Send a response to a request."""
        # Caller should look up original request to get sender
        if request_id in self._pending_responses:
            self._response_results[request_id] = result
            self._pending_responses[request_id].set()

    def shutdown(self):
        """Shutdown the mailbox."""
        self.send(Message(message_type=MessageType.SHUTDOWN, sender="system", receiver=self.agent_id))


class MessageBroker:
    """Routes messages between agents."""

    def __init__(self):
        self._mailboxes = {}  # agent_id -> AgentMailbox
        self._request_map = {}  # request_id -> (sender, receiver)

    def register_agent(self, agent_id: str, mailbox: AgentMailbox):
        """Register an agent's mailbox."""
        self._mailboxes[agent_id] = mailbox

    def route(self, message: Message):
        """Route a message to its receiver."""
        if message.receiver not in self._mailboxes:
            raise ValueError(f"Agent {message.receiver} not found")

        if message.message_type == MessageType.REQUEST:
            self._request_map[message.request_id] = (message.sender, message.receiver)

        self._mailboxes[message.receiver].send(message)

    def route_response(self, request_id: str, result: Any, error: Optional[str] = None):
        """Route a response back to the requester."""
        if request_id not in self._request_map:
            raise ValueError(f"Request {request_id} not found")

        sender, receiver = self._request_map.pop(request_id)

        response = Message(
            message_type=MessageType.RESPONSE if error is None else MessageType.ERROR,
            sender=receiver,
            receiver=sender,
            request_id=request_id,
            result=result,
            error=error,
        )

        self._mailboxes[sender].send(response)
        # Also set the event in the sender's mailbox for request/response pattern
        if request_id in self._mailboxes[sender]._pending_responses:
            self._mailboxes[sender]._response_results[request_id] = result
            self._mailboxes[sender]._pending_responses[request_id].set()


# Global message broker instance
_message_broker = MessageBroker()


def get_message_broker() -> MessageBroker:
    """Get the global message broker."""
    return _message_broker
