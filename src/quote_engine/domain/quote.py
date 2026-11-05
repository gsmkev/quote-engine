from dataclasses import dataclass, field
from typing import Any, Literal


class DomainError(Exception):
    pass


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class SetQty:
    sku: str
    qty: int


@dataclass(frozen=True)
class AddLine:
    sku: str
    qty: int


@dataclass(frozen=True)
class RemoveLine:
    sku: str


@dataclass(frozen=True)
class LinkConversation:
    conversation_id: str


Op = Cancel | SetQty | AddLine | RemoveLine | LinkConversation


@dataclass(frozen=True)
class Cause:
    message_id: str | None
    review_id: int | None = None


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]
    cause: Cause


@dataclass
class Line:
    qty: int
    position: int


@dataclass
class Quote:
    id: str
    customer_id: str
    status: Literal["draft", "cancelled"] = "draft"
    version: int = 1
    lines: dict[str, Line] = field(default_factory=dict)
    conversations: set[str] = field(default_factory=set)
    pending_events: list[Event] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        id: str,
        customer_id: str,
        lines: list[tuple[str, int]],
        conversation_id: str,
        cause: Cause,
    ) -> "Quote":
        q = cls(id, customer_id)
        q.pending_events.append(Event("QuoteCreated", {"customer_id": customer_id}, cause))
        q.apply([AddLine(sku, qty) for sku, qty in lines], cause, bump=False)
        q.apply([LinkConversation(conversation_id)], cause, bump=False)
        return q

    def apply(self, ops: list[Op], cause: Cause, bump: bool = True) -> None:
        # Plan against copies so the whole batch is all-or-nothing.
        qtys = {sku: line.qty for sku, line in self.lines.items()}
        positions = {sku: line.position for sku, line in self.lines.items()}
        convs = set(self.conversations)
        status = self.status
        events: list[tuple[str, dict[str, Any]]] = []

        for op in ops:
            if status != "draft":
                raise DomainError(f"quote {self.id} is {status}")
            match op:
                case Cancel():
                    status = "cancelled"
                    events.append(("QuoteCancelled", {}))
                case AddLine(sku, qty):
                    _check_qty(qty)
                    if sku in qtys:
                        raise DomainError(f"line {sku} already exists")
                    qtys[sku] = qty
                    positions[sku] = max(positions.values(), default=-1) + 1
                    events.append(("LineAdded", {"sku": sku, "qty": qty}))
                case SetQty(sku, qty):
                    _check_qty(qty)
                    if sku not in qtys:
                        raise DomainError(f"line {sku} not found")
                    if qtys[sku] != qty:
                        events.append(
                            ("LineQtyChanged", {"sku": sku, "from": qtys[sku], "to": qty})
                        )
                        qtys[sku] = qty
                case RemoveLine(sku):
                    if sku not in qtys:
                        raise DomainError(f"line {sku} not found")
                    events.append(("LineRemoved", {"sku": sku, "qty": qtys.pop(sku)}))
                    del positions[sku]
                case LinkConversation(conversation_id):
                    if conversation_id not in convs:
                        convs.add(conversation_id)
                        events.append(("ConversationLinked", {"conversation_id": conversation_id}))

        self.status = status
        self.lines = {sku: Line(qty, positions[sku]) for sku, qty in qtys.items()}
        self.conversations = convs
        self.pending_events.extend(Event(t, p, cause) for t, p in events)
        if events and bump:
            self.version += 1

    def line_items(self) -> list[tuple[str, int]]:
        ordered = sorted(self.lines.items(), key=lambda kv: kv[1].position)
        return [(sku, line.qty) for sku, line in ordered]


def _check_qty(qty: int) -> None:
    if qty <= 0:
        raise DomainError(f"qty must be > 0, got {qty}")
