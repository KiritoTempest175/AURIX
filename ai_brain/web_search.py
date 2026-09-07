"""AURIX AI Brain — Web Search Integration.

Scrapes DuckDuckGo HTML search results and synthesizes a summarized
answer using the local LLM.
"""

import logging
import requests
from bs4 import BeautifulSoup
from typing import Any

logger = logging.getLogger("aurix.ai_brain.web_search")

class WebSearcher:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def search(self, query: str, llm_runner: Any) -> str:
        """Perform a web search and synthesize the result."""
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        
        try:
            response = requests.post(url, data=data, headers=self.headers, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch search results: {e}")
            return f"Failed to connect to the web search service: {e}"

        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.find_all('div', class_='result')
        
        snippets = []
        for res in results[:5]:  # Top 5 results
            title_elem = res.find('a', class_='result__a')
            snippet_elem = res.find('a', class_='result__snippet')
            if title_elem and snippet_elem:
                title = title_elem.text.strip()
                snippet = snippet_elem.text.strip()
                snippets.append(f"Title: {title}\nSnippet: {snippet}")

        if not snippets:
            return "No web search results found."

        context = "\n\n".join(snippets)
        prompt = (
            f"You are synthesizing web search results to answer a user's query.\n"
            f"Query: {query}\n\n"
            f"Search Results:\n{context}\n\n"
            f"Provide a concise, direct answer to the query based ONLY on the provided search results."
        )

        try:
            # We bypass the standard context history for this synthesis
            formatted = llm_runner.format_prompt(
                user_input=prompt,
                sys_prompt="You are a helpful AI that summarizes search results. Keep it brief and accurate.",
                context_history=[]
            )
            answer = llm_runner.generate_response(formatted, max_new_tokens=256)
            return answer
        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            # Fallback to just giving the first snippet
            return f"Search result: {snippets[0]}"
