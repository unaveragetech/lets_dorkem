"""Lightweight tool-calling framework for DorkAgent.

Tools are Python callables exposed to the LLM as structured descriptions.
The LLM can invoke them via <tool_call> XML blocks embedded in its text
response, or the agent can call them directly with LLM-supplied arguments.

Example LLM output invoking a tool:
    <tool_call name="filter_dorks_by_topic">{"topic": "admin login", "max": 15}</tool_call>
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional


class ToolDefinition:
    """Metadata and callable for a single agent tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, str],
        func: Callable[..., Any],
    ) -> None:
        self.name = name
        self.description = description
        # {param_name: "type — human description"}
        self.parameters = parameters
        self.func = func

    def to_prompt_str(self) -> str:
        params = "\n".join(f"    {k}: {v}" for k, v in self.parameters.items())
        return (
            f"  [{self.name}]\n"
            f"  Description: {self.description}\n"
            f"  Parameters:\n{params}"
        )

    def execute(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


class ToolRegistry:
    """Container for ToolDefinitions with prompt generation and call parsing."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def prompt_section(self) -> str:
        """Return a prompt block describing all tools the LLM may call."""
        lines = [
            "## Available Tools",
            "Call a tool by including an XML block in your response:",
            '  <tool_call name="TOOL_NAME">{"arg1": "value1"}</tool_call>',
            "",
        ]
        for tool in self._tools.values():
            lines.append(tool.to_prompt_str())
        return "\n".join(lines)

    def execute_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Find and execute every <tool_call> block embedded in *text*."""
        results: List[Dict[str, Any]] = []
        pattern = re.compile(
            r'<tool_call\s+name="([^"]+)">(.*?)</tool_call>',
            re.DOTALL,
        )
        for match in pattern.finditer(text):
            tool_name = match.group(1)
            raw_args = match.group(2).strip()
            tool = self._tools.get(tool_name)
            if tool is None:
                results.append({"tool": tool_name, "error": "unknown tool", "success": False})
                continue
            try:
                args: Dict[str, Any] = json.loads(raw_args) if raw_args else {}
                result = tool.execute(**args)
                results.append({"tool": tool_name, "result": result, "success": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"tool": tool_name, "error": str(exc), "success": False})
        return results


# ---------------------------------------------------------------------------
# Factory functions for standard DorkAgent tools
# ---------------------------------------------------------------------------


def make_filter_dorks_tool(all_dorks: List[str]) -> ToolDefinition:
    """Build a tool that filters the dork list by keyword topic."""

    def filter_dorks_by_topic(topic: str, max: int = 20) -> List[str]:
        topic_lower = topic.lower()
        words = [w for w in topic_lower.split() if len(w) > 2]
        if not words:
            return all_dorks[:max]
        scored: List[tuple[int, str]] = []
        for dork in all_dorks:
            score = sum(1 for w in words if w in dork.lower())
            if score > 0:
                scored.append((score, dork))
        scored.sort(reverse=True)
        return [d for _, d in scored[:max]]

    return ToolDefinition(
        name="filter_dorks_by_topic",
        description="Filter the available dorks to those most relevant to a topic or category keyword.",
        parameters={
            "topic": 'str — topic to filter by, e.g. "sql database" or "admin login"',
            "max": "int — maximum number of dorks to return (default 20)",
        },
        func=filter_dorks_by_topic,
    )


def make_expand_query_tool(llm_generate: Callable[[str], str]) -> ToolDefinition:
    """Build a tool that asks the LLM to generate query variations."""

    def expand_query(base_query: str, goal: str, count: int = 5) -> List[str]:
        prompt = (
            f"Goal: {goal}\n"
            f"Base query: {base_query}\n\n"
            f"Generate {count} variations of the base query suitable for Google dorking. "
            "Return one variation per line, no numbering, no explanation."
        )
        try:
            response = llm_generate(prompt)
            return [line.strip() for line in response.splitlines() if line.strip()][:count]
        except Exception:  # noqa: BLE001
            return [base_query]

    return ToolDefinition(
        name="expand_query",
        description="Generate variations of a Google dork query to broaden search coverage.",
        parameters={
            "base_query": "str — the base dork query to expand",
            "goal": "str — the research goal for context",
            "count": "int — number of variations to generate (default 5)",
        },
        func=expand_query,
    )


def make_get_dork_categories_tool(all_dorks: List[str]) -> ToolDefinition:
    """Build a tool that returns the distribution of dork categories."""

    def get_dork_categories() -> Dict[str, int]:
        categories: Dict[str, int] = {}
        keywords = [
            "intitle", "inurl", "intext", "filetype", "site",
            "ext", "cache", "link", "related",
        ]
        for dork in all_dorks:
            for kw in keywords:
                if kw + ":" in dork.lower():
                    categories[kw] = categories.get(kw, 0) + 1
                    break
            else:
                categories["other"] = categories.get("other", 0) + 1
        return dict(sorted(categories.items(), key=lambda x: x[1], reverse=True))

    return ToolDefinition(
        name="get_dork_categories",
        description="Return a count of available dorks grouped by their operator type (intitle, filetype, etc.).",
        parameters={},
        func=get_dork_categories,
    )
