from dataclasses import asdict, dataclass, field


@dataclass
class ServiceResult:
    action: str
    success: bool
    message: str = ""
    skipped: bool = False
    data: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class AgentEvent:
    intent: str
    source: str = "cli"
    locale: str = "am"
    payload: dict = field(default_factory=dict)
