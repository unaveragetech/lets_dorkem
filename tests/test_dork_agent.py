import tempfile
import unittest
from pathlib import Path

from dork_agent.agent import DorkAgent
from dork_agent.dork_loader import load_dorks
from dork_agent.review_writer import write_review
from dork_agent.source import load_source_urls, parse_dorks_from_html, parse_dorks_from_text


class DummyModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        return 'intitle:"index of" "parent directory"'


class DummySearcher:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def search(self, query: str, max_results: int | None = None):
        return [
            {
                "title": "Example Page",
                "url": "http://example.com/test",
                "snippet": "Sample snippet for testing.",
            }
        ]


class DorkAgentTests(unittest.TestCase):
    def test_load_dorks_returns_nonempty_list(self):
        dorks = load_dorks()
        self.assertIsInstance(dorks, list)
        self.assertGreater(len(dorks), 0)

    def test_write_review_creates_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            review_path = Path(tmpdir) / "review.md"
            write_review(
                review_path,
                goal="Test goal",
                selected_dorks=["intitle:\"index of\" \"parent directory\""],
                findings=[
                    {
                        "query": "intitle:\"index of\" \"parent directory\"",
                        "results": [
                            {
                                "title": "Test Page",
                                "url": "http://example.com",
                                "snippet": "A snippet.",
                            }
                        ],
                    }
                ],
                metadata={"small_model": "dummy", "large_model": "dummy"},
            )
            self.assertTrue(review_path.exists())
            content = review_path.read_text(encoding="utf-8")
            self.assertIn("# Google Dork Review", content)
            self.assertIn("Test goal", content)
            self.assertIn("http://example.com", content)

    def test_agent_run_with_mocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            review_path = Path(tmpdir) / "review.md"
            agent = DorkAgent(
                goal="Find exposed directories",
                small_model_client=DummyModel("small-model"),
                large_model_client=DummyModel("large-model"),
                searcher=DummySearcher(),
                review_path=str(review_path),
                dork_file=str(Path("data/google_hacking_database.txt")),
                max_results=1,
            )
            result = agent.run(max_selections=1)
            self.assertTrue(review_path.exists())
            self.assertEqual(result["review_path"], str(review_path))
            self.assertEqual(len(result["selected_dorks"]), 1)
            self.assertEqual(result["findings"][0]["results"][0]["url"], "http://example.com/test")

    def test_parse_dorks_from_html(self):
        html = '<td>intitle:"index of" "backup"</td>'
        dorks = parse_dorks_from_html(html)
        self.assertIn('intitle:"index of" "backup"', dorks)

    def test_parse_dorks_from_text(self):
        text = '# comment\nintitle:"index of" "backup"\nfiletype:sql "INSERT INTO"\n'
        dorks = parse_dorks_from_text(text)
        self.assertEqual(len(dorks), 2)
        self.assertIn('filetype:sql "INSERT INTO"', dorks)

    def test_load_source_urls_defaults(self):
        urls = load_source_urls()
        self.assertIsInstance(urls, list)
        self.assertGreater(len(urls), 0)


if __name__ == "__main__":
    unittest.main()
