"""Tests for tools.py, sub_agent.py, and OllamaClient.list_models()."""
import unittest
import json
from unittest.mock import patch, MagicMock


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        from dork_agent.tools import (
            ToolRegistry,
            make_filter_dorks_tool,
            make_get_dork_categories_tool,
        )
        self.dorks = [
            "site:example.com filetype:pdf",
            "intitle:index.of password",
            "inurl:admin login",
            "filetype:sql dump",
        ]
        self.reg = ToolRegistry()
        self.reg.register(make_filter_dorks_tool(self.dorks))
        self.reg.register(make_get_dork_categories_tool(self.dorks))

    def test_prompt_section_contains_tool_names(self):
        section = self.reg.prompt_section()
        self.assertIn("filter_dorks_by_topic", section)
        self.assertIn("get_dork_categories", section)

    def test_filter_dorks_by_topic_returns_matches(self):
        # tool takes 'topic' (str), not 'keywords'
        xml = '<tool_call name="filter_dorks_by_topic">{"topic": "admin login"}</tool_call>'
        results = self.reg.execute_from_text(xml)
        self.assertEqual(len(results), 1)
        data = results[0]
        self.assertTrue(data["success"])
        self.assertEqual(data["tool"], "filter_dorks_by_topic")
        matched = data["result"]
        self.assertTrue(any("admin" in d or "login" in d for d in matched))

    def test_filter_dorks_no_match_returns_empty(self):
        xml = '<tool_call name="filter_dorks_by_topic">{"topic": "zzznomatch999"}</tool_call>'
        results = self.reg.execute_from_text(xml)
        self.assertEqual(len(results), 1)
        data = results[0]
        self.assertTrue(data["success"])
        matched = data["result"]
        self.assertIsInstance(matched, list)
        # No keywords match → empty list (not fallback)
        self.assertEqual(matched, [])

    def test_get_dork_categories_returns_dict(self):
        xml = '<tool_call name="get_dork_categories">{}</tool_call>'
        results = self.reg.execute_from_text(xml)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        cats = results[0]["result"]
        self.assertIsInstance(cats, dict)
        # Should have operator keys (site, intitle, inurl, filetype, etc.)
        self.assertTrue(len(cats) > 0)

    def test_execute_from_text_unknown_tool(self):
        xml = '<tool_call name="nonexistent_tool">{"x": 1}</tool_call>'
        results = self.reg.execute_from_text(xml)
        # Unknown tools return an error entry, not silently ignored
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])
        self.assertEqual(results[0]["error"], "unknown tool")

    def test_execute_from_text_no_calls(self):
        results = self.reg.execute_from_text("Just some plain text with no tool calls.")
        self.assertEqual(results, [])


class TestExpandQueryTool(unittest.TestCase):
    def test_expand_query_calls_llm(self):
        from dork_agent.tools import ToolRegistry, make_expand_query_tool

        generated = []

        def fake_generate(prompt):
            generated.append(prompt)
            return "inurl:admin\nsite:target.com filetype:log\nintitle:config"

        reg = ToolRegistry()
        reg.register(make_expand_query_tool(fake_generate))

        # expand_query takes 'base_query' and 'goal'
        xml = '<tool_call name="expand_query">{"base_query": "inurl:admin", "goal": "find admin panels"}</tool_call>'
        results = reg.execute_from_text(xml)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        expanded = results[0]["result"]
        self.assertIsInstance(expanded, list)
        self.assertTrue(len(expanded) >= 1)
        self.assertEqual(len(generated), 1)  # LLM was called once


class TestPaginate(unittest.TestCase):
    def test_paginate_even(self):
        from dork_agent.sub_agent import paginate
        pages = paginate(list(range(20)), page_size=10)
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0], list(range(10)))
        self.assertEqual(pages[1], list(range(10, 20)))

    def test_paginate_with_remainder(self):
        from dork_agent.sub_agent import paginate
        pages = paginate(list(range(15)), page_size=10)
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(pages[1]), 5)

    def test_paginate_empty(self):
        from dork_agent.sub_agent import paginate
        self.assertEqual(paginate([], page_size=10), [])

    def test_paginate_smaller_than_page(self):
        from dork_agent.sub_agent import paginate
        pages = paginate([1, 2, 3], page_size=10)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0], [1, 2, 3])


class TestSearchSubAgent(unittest.TestCase):
    def test_run_success(self):
        from dork_agent.sub_agent import SearchSubAgent

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [
            {"url": "http://a.com", "title": "A"},
            {"url": "http://b.com", "title": "B"},
        ]

        # Actual signature: (dork, goal, searcher, browser_instructions='', tab_id=0)
        agent = SearchSubAgent(dork="inurl:admin", goal="find admin panels", searcher=mock_searcher, tab_id=1)
        result = agent.run()

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["tab_id"], 1)
        self.assertEqual(result["dork"], "inurl:admin")
        self.assertEqual(result["result_count"], 2)
        self.assertIn("elapsed", result)

    def test_run_error(self):
        from dork_agent.sub_agent import SearchSubAgent

        mock_searcher = MagicMock()
        mock_searcher.search.side_effect = RuntimeError("Search failed")

        agent = SearchSubAgent(dork="site:evil.com", goal="test", searcher=mock_searcher, tab_id=2)
        result = agent.run()

        self.assertEqual(result["status"], "error")
        self.assertIn("Search failed", result["error"])


class TestListModels(unittest.TestCase):
    def test_list_models_parses_output(self):
        from dork_agent.ollama_client import OllamaClient

        fake_output = (
            "NAME                ID        SIZE\n"
            "llama3:latest       abc123    4.1 GB\n"
            "mistral:7b          def456    3.8 GB\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
            models = OllamaClient.list_models()

        self.assertEqual(models, ["llama3:latest", "mistral:7b"])

    def test_list_models_empty_on_error(self):
        from dork_agent.ollama_client import OllamaClient
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.SubprocessError("ollama not found")):
            models = OllamaClient.list_models()

        self.assertEqual(models, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
