import logging
import os

from a2a.server.agent_execution import AgentExecutor as A2AAgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import InternalError, Part, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from agent import WarehouseAgent
from load_skill_resources import get_load_skill_resource_tool

if os.environ.get("JOULE_RUNTIME"):
    from mcp_tools import get_mcp_tools, get_tok

logger = logging.getLogger(__name__)


def _extract_user_identity(context: RequestContext) -> str | None:
    try:
        auth_header = getattr(context, "authorization", None) or ""
        if auth_header.lower().startswith("bearer ") and len(auth_header) > 7:
            import base64
            import json
            parts = auth_header[7:].split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                claims = json.loads(base64.b64decode(padded))
                return claims.get("sub") or claims.get("user_name") or claims.get("email")
    except Exception:
        pass
    return None


class AgentExecutor(A2AAgentExecutor):
    def __init__(self):
        self.agent = WarehouseAgent()
        self.skill_tools = get_load_skill_resource_tool()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        user_id = _extract_user_identity(context)
        extra_tools = list(self.skill_tools)

        if os.environ.get("JOULE_RUNTIME"):
            try:
                tok = get_tok(context)
                mcp_tools = await get_mcp_tools(tok=tok)
                if mcp_tools:
                    logger.info(
                        "Loaded %d MCP tool(s) from Agent Gateway: %s",
                        len(mcp_tools),
                        [t.name for t in mcp_tools],
                    )
                    extra_tools.extend(mcp_tools)
            except Exception as e:
                logger.error("Failed to load MCP tools from Agent Gateway: %s", e)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        try:
            async for item in self.agent.stream(
                query,
                task.context_id,
                user_id=user_id,
                extra_tools=extra_tools,
            ):
                is_task_complete = item["is_task_complete"]
                require_user_input = item["require_user_input"]
                content = item["content"]

                if require_user_input:
                    await updater.update_status(
                        TaskState.input_required,
                        new_agent_text_message(content, task.context_id, task.id),
                        final=True,
                    )
                    break
                elif is_task_complete:
                    await updater.add_artifact(
                        [Part(root=TextPart(text=content))], name="agent_result"
                    )
                    await updater.complete()
                    break
                else:
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(content, task.context_id, task.id),
                    )
        except Exception as e:
            logger.exception("Agent execution error")
            raise ServerError(error=InternalError()) from e

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())
