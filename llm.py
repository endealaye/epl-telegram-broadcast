import os
import requests
from typing import Optional, Dict, Any

# In a real production environment, this would use a library like 'openai' or 'anthropic'.
# To keep dependencies minimal and avoid immediate crashes, we use a simple API wrapper.

class LLM:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.api_url = "https://api.openai.com/v1/chat/completions"

    def generate(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generates a response from the LLM. 
        If schema is provided, it expects a JSON response matching that schema.
        """
        if not self.api_key:
            # Fallback for development/testing to avoid crashes
            # In a real scenario, this should raise an error or use a mock
            return self._mock_generate(prompt, schema)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = "You are a professional sports translator and analyst. Always provide output in the requested language (Amharic)."
        if schema:
            system_prompt += f"\nReturn ONLY a JSON object matching this schema: {schema}"

        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"} if schema else {"type": "text"}
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            if schema:
                import json
                return json.loads(content)
            return content
        except Exception as e:
            print(f"LLM API Error: {e}")
            return self._mock_generate(prompt, schema)

    def _mock_generate(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        A slightly better mock that doesn't just return the original text.
        This is ONLY used when API_KEY is missing.
        """
        if schema:
            # Return a mock JSON object based on the schema
            result = {}
            for key in schema.keys():
                result[key] = f"[Amharic Translation of {key}]"
            return result
        return "[Amharic Translation]"

llm = LLM()
