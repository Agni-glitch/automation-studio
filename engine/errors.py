"""Exception hierarchy for the workflow engine."""

from __future__ import annotations


class EngineError(Exception):
    """Base class for all engine errors."""


class WorkflowValidationError(EngineError):
    """The workflow definition is structurally invalid (cycles, unknown nodes, bad params...)."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("Invalid workflow: " + "; ".join(self.errors))


class UnknownNodeTypeError(EngineError):
    """A node type is not present in the registry."""


class NodeExecutionError(EngineError):
    """Raised by nodes to signal a failure. Retried according to the node's retry policy."""


class NonRetryableError(NodeExecutionError):
    """A failure that will not succeed on retry (bad config, missing credential...)."""


class ExpressionError(NonRetryableError):
    """A ``{{ ... }}`` expression in node parameters could not be resolved."""


class CredentialNotFoundError(NonRetryableError):
    """A credential referenced by a node does not exist or is not assigned."""


class NodeTimeoutError(NodeExecutionError):
    """A node exceeded its ``timeout_seconds``."""
