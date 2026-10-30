class WardenError(Exception):
    """Base for all Warden exceptions."""


class PolicyDenyError(WardenError):
    def __init__(self, reason: str, agent_id: str, pack: str):
        self.reason = reason
        self.agent_id = agent_id
        self.pack = pack
        super().__init__(f"policy deny: {reason} (agent={agent_id}, pack={pack})")


class VaultError(WardenError):
    pass


class DetectionError(WardenError):
    pass


class AuthorityError(WardenError):
    pass


class GatewayError(WardenError):
    pass
