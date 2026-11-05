from quote_engine.application.ports import ConversationCtx, Extractor, MessageCtx
from quote_engine.domain.interpretation import ConversationExtraction, MessageInterpretation


class CascadeExtractor:
    """Cheap extractor first, fallback only when it gives up; conversations go to the fallback."""

    def __init__(self, first: Extractor, fallback: Extractor | None) -> None:
        self.first = first
        self.fallback = fallback

    async def interpret(self, ctx: MessageCtx) -> MessageInterpretation | None:
        result = await self.first.interpret(ctx)
        if result is None and self.fallback is not None:
            result = await self.fallback.interpret(ctx)
        return result

    async def extract_conversation(self, ctx: ConversationCtx) -> ConversationExtraction | None:
        return None if self.fallback is None else await self.fallback.extract_conversation(ctx)
