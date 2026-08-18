from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    risk: str
    description: str


CAPABILITIES = {
    "workspace.list": Capability("workspace.list", "low", "List the Ventor workspace"),
    "workspace.read": Capability("workspace.read", "medium", "Read a file inside the workspace"),
    "workspace.write": Capability("workspace.write", "high", "Write a file inside the workspace"),
    "process.safe": Capability("process.safe", "high", "Run an allowlisted command inside the required sandbox"),
    "browser.open": Capability("browser.open", "high", "Open a public http(s) page with the isolated browser"),
    "research.web": Capability("research.web", "high", "Perform bounded public-web research and return source evidence"),
}


def authorize(name: str, owner: bool, confirmed: bool = False):
    capability = CAPABILITIES.get(name)
    if not capability:
        return False, "unknown_capability"
    if not owner:
        return False, "owner_required"
    if capability.risk in {"high", "critical"} and not confirmed:
        return False, "confirmation_required"
    return True, "ok"
