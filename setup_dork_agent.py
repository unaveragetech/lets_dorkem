import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from dork_agent.config import DEFAULT_SETTINGS, save_settings


def prompt(text: str, default: str) -> str:
    answer = input(f"{text} [{default}]: ").strip()
    return answer or default


def prompt_int(text: str, default: int) -> int:
    answer = input(f"{text} [{default}]: ").strip()
    if not answer:
        return default
    try:
        return int(answer)
    except ValueError:
        print("Invalid number. Using default.")
        return default


def prompt_choice(text: str, choices: list[str], default: str) -> str:
    choices_text = "/".join(choices)
    answer = input(f"{text} ({choices_text}) [{default}]: ").strip().lower()
    if not answer:
        return default
    if answer in choices:
        return answer
    print(f"Invalid choice: {answer}. Using default {default}.")
    return default


def is_command_available(name: str) -> bool:
    return shutil.which(name) is not None


def is_package_installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def run_command(command: list[str], capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )


def install_requirements() -> None:
    print("Installing Python dependencies from requirements.txt...")
    command = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    process = run_command(command)
    print(process.stdout)
    if process.returncode != 0:
        print(process.stderr)
        raise RuntimeError("Dependency installation failed.")


def install_playwright() -> None:
    print("Installing Playwright browser drivers...")
    command = [sys.executable, "-m", "playwright", "install"]
    process = run_command(command)
    print(process.stdout)
    if process.returncode != 0:
        print(process.stderr)
        raise RuntimeError("Playwright installation failed.")


def main() -> None:
    print("=== Google Dork Agent Setup Wizard ===\n")
    settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()

    settings["browser_backend"] = prompt_choice(
        "Choose browser automation backend", ["selenium", "playwright"], settings["browser_backend"]
    )
    settings["small_model"] = prompt("Small Ollama model name", settings["small_model"])
    settings["large_model"] = prompt("Large Ollama model name", settings["large_model"])
    settings["dork_file"] = prompt("Local dork file path", settings["dork_file"])
    settings["review_path"] = prompt("Generated review output path", settings["review_path"])
    settings["max_results"] = prompt_int("Max search results per dork", settings["max_results"])

    if not is_command_available("ollama"):
        print("\nWARNING: Ollama CLI was not found on your PATH.")
        print("Install Ollama locally and ensure the `ollama` command is available before running the agent.")
    else:
        print("\nOllama CLI found.")

    if settings["browser_backend"] == "playwright":
        if not is_package_installed("playwright"):
            print("\nPlaywright is not installed.")
            install = input("Install Playwright now? (y/N): ").strip().lower() == "y"
            if install:
                install_requirements()
                install_playwright()
        else:
            print("\nPlaywright package is installed.")
    else:
        if not is_package_installed("selenium"):
            print("\nSelenium is not installed. Installing now...")
            install_requirements()
        else:
            print("\nSelenium package is installed.")

    dork_path = Path(settings["dork_file"])
    if not dork_path.exists():
        print(f"\nWARNING: Dork file does not exist at {dork_path}")
        print("Create the file or update the path in settings.json after setup.")

    save_settings(settings)
    print(f"\nSetup complete. Settings written to {Path('dork_agent') / 'settings.json'}")
    print("You can now run: python run_dork_agent.py --goal \"Your target objective\"")


if __name__ == "__main__":
    main()
