import json
import subprocess
import urllib.request
from typing import Any, Callable, List, Optional


class OllamaClient:
    # Base URL for the Ollama REST API (used for streaming)
    API_BASE = "http://127.0.0.1:11434"

    def __init__(self, model: str) -> None:
        self.model = model

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        """Run a prompt through the model and return the text response."""
        try:
            completed = subprocess.run(
                ["ollama", "run", self.model, prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Ollama CLI not found. Install ollama and ensure it is on PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Ollama generation failed: {exc.stderr.strip() or exc.stdout.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Ollama request timed out after 120 seconds.") from exc

        return completed.stdout.strip()

    def generate_stream(
        self,
        prompt: str,
        on_token: Optional[Callable[[str], None]] = None,
        temperature: float = 0.2,
    ) -> str:
        """Stream tokens from Ollama REST API, calling on_token for each chunk.

        Falls back to generate() if the REST API is unreachable.
        Returns the full accumulated response when done.
        """
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.API_BASE}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            chunks: List[str] = []
            with urllib.request.urlopen(req, timeout=180) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = obj.get("response", "")
                    if token:
                        chunks.append(token)
                        if on_token:
                            on_token(token)
                    if obj.get("done"):
                        break
            return "".join(chunks).strip()
        except Exception:
            # REST API unavailable — fall back to subprocess (non-streaming)
            result = self.generate(prompt, temperature=temperature)
            if on_token:
                on_token(result)
            return result

    def generate_json(self, prompt: str, temperature: float = 0.2) -> Any:
        """Run a prompt and attempt to parse the response as JSON.
        Returns the parsed object, or the raw string if parsing fails."""
        output = self.generate(prompt, temperature=temperature)
        # Strip markdown fences that some models wrap output in
        cleaned = output.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            cleaned = "\n".join(inner)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return output

    @staticmethod
    def list_models() -> List[str]:
        """Return the names of all locally installed Ollama models."""
        try:
            completed = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=10,
            )
        except Exception:
            return []

        models: List[str] = []
        for line in completed.stdout.splitlines()[1:]:  # first line is the header
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
