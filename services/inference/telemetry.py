from dataclasses import dataclass, field


@dataclass
class InferenceTelemetry:
    events: list[dict] = field(default_factory=list)

    def record(self, **event):
        self.events.append(event)