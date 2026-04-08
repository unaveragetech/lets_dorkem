# Google Dorks Showcase

Welcome to the **Google Dorks Showcase**! This repository is designed to explore and demonstrate the powerful capabilities of Google Dorks—advanced search techniques that can unearth hidden information within Google's search index. Whether you're a cybersecurity professional, researcher, or just someone intrigued by advanced search strategies, this repository will equip you with the knowledge and tools to make the most of Google Dorks.

## What Are Google Dorks?

Google Dorks, or Google Hacking, utilize advanced search operators to refine and target search queries beyond what is achievable with basic searches. These operators enable users to discover specific data, locate hidden content, and perform comprehensive searches that might otherwise remain concealed.

## Purpose of This Repository

The **Google Dorks Showcase** serves several key purposes:

- **Educate**: Provide an in-depth guide on Google Dorks and their syntax. Learn how to effectively use advanced search operators to narrow your search results and uncover hidden data.
- **Demonstrate**: Offer practical examples of Google Dorks in action. Understand real-world applications and see how these queries can be applied for various purposes, from enhancing cybersecurity to conducting detailed research.
- **Empower**: Equip you with the knowledge to use Google Dorks responsibly and effectively. Learn about the ethical considerations and best practices to ensure your use of these techniques remains professional and legal.

## Features

- **Detailed Explanations**: Each dork query is accompanied by a clear explanation of its function, syntax, and potential applications.
- **Practical Examples**: Real-world examples illustrate how to use each dork to find specific types of information.
- **Ethical Guidelines**: Advice on responsible use of Google Dorks to ensure compliance with privacy laws and ethical standards.

## HTML-Based Search Engine

In addition to Google Dorks, this repository includes an **HTML-Based Search Engine** designed to enhance your search experience. The search engine features:

- **Multi-Search Engine Support**: Search across multiple engines including Google, Perplexity AI, Bing, DuckDuckGo, and Wikipedia.
- **Autocomplete**: Get search suggestions based on your previous queries.
- **Voice Search**: Conduct searches using voice commands (requires browser support for Web Speech API).
- **Dark/Light Mode Toggle**: Switch between dark and light themes for comfortable reading.

### Features and Capabilities

- **Custom Search Queries**: Prefix your queries with specific identifiers (e.g., `G-` for Google, `P-` for Perplexity) to search directly with your preferred engine.
- **Search History**: Save and access your recent searches for quick re-use.
- **Responsive Design**: Optimized for various screen sizes to ensure usability on both desktop and mobile devices.

-Hosted the html here 
-https://unaveragetech.github.io/Dorkem_html/
### Code Overview

Here's a snippet from the provided HTML-based search engine code:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Meta tags and styling here -->
</head>
<body>
    <div class="watermark">Q&AI</div>
    <button id="mode-toggle">🌓</button>
    <div class="tagline">Search Everywhere, Answer Everything</div>
    <div class="search-options">
        <label><input type="checkbox" name="engine" value="google" checked> Google</label>
        <!-- More search engines here -->
    </div>
    <div class="search-container">
        <input type="text" id="search-input" placeholder="Enter your search query" autofocus>
        <button id="voice-search">🎤</button>
        <button id="search-button">
            <!-- SVG icon for search button -->
        </button>
        <div id="autocomplete"></div>
    </div>
    <script>
        // JavaScript for handling search, autocomplete, and voice input
    </script>
</body>
</html>
```

## Getting Started

1. **Explore the Repository**: Navigate through the various sections to understand different types of Google Dorks and their applications.
2. **Utilize the HTML-Based Search Engine**: Use the provided HTML file to test the multi-search capabilities and other features.
3. **Experiment and Learn**: Apply the examples and techniques to your own searches and adapt them to your needs.

## Automating Google Dork Discovery

A new Python-based agent has been added to this repository to automate Google Dork selection, browser search execution, and report generation.

### What it does

- Loads a local Google Hacking Database dataset from `data/google_hacking_database.txt`
- Uses a small local Ollama model to capture or refine the search objective
- Uses a larger local Ollama model to select the most relevant dorks for the goal
- Executes browser-based Google searches and scrapes the top result links
- Writes a structured `review.md` report containing selected dorks and notable pages

### How to run

1. Install Python dependencies:

```bash
pip install -r requirements.txt
playwright install
```

> If you want the newest browser automation experience, install `browser-use` as well. It is already included in `requirements.txt`.

2. Run the setup wizard first to configure models and backend support:

```bash
python setup_dork_agent.py
```

3. Start the interactive UI server:

```bash
python ui_server.py
```

4. Open your browser to `http://127.0.0.1:8000/Index.html`.

5. Optionally run the slow crawl wizard to extract dorks from Exploit-DB page-by-page:

```bash
python crawl_wizard.py
```

6. Refresh remote Google dork sources to cache additional search rules:

```bash
python run_dork_agent.py --refresh-sources
```

5. Browse the available dorks from local and remote sources:

```bash
python run_dork_agent.py --browse-dorks --limit 50
```

6. Run the agent to generate a `review.md` report:

```bash
python run_dork_agent.py --goal "Find exposed admin portals and configuration leaks" --max-selections 8
```

6. Open the generated `review.md` to review selected dorks, results, and notable links.

### Testing

Run the built-in tests with:

```bash
python -m unittest discover tests
```

### Notes

- The agent assumes local Ollama CLI models are available and on your PATH.
- You can choose the browser automation backend: `playwright`, `selenium`, or `browser-use`.
- If you prefer Selenium instead of Playwright, use `--browser-backend selenium`.
- Expand `data/google_hacking_database.txt` with more Exploit-DB queries for broader coverage.

## Contributing

Contributions are welcome! If you have additional Google Dorks, examples, or suggestions for improvements, please submit a pull request or open an issue. Your input helps enhance the repository and benefits the community.

## Disclaimer

While Google Dorks offer powerful capabilities for finding information, they should be used responsibly. Avoid accessing or exploiting sensitive information without proper authorization. Respect privacy and adhere to legal guidelines.

## License

This repository is licensed under the [MIT License](LICENSE). Feel free to use and modify the content, but please attribute the original source.

---

We hope you find this repository useful and informative. Explore the power of Google Dorks and enhance your search capabilities with our tools and examples!

Happy Searching! 🚀
