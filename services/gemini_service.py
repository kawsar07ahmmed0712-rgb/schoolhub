from __future__ import annotations

import os
from typing import Optional

import google.generativeai as genai


class GeminiClient:
    def __init__(self) -> None:
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"').strip("'")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def ask(self, prompt: str, student_name: Optional[str] = None) -> str:
        system = (
            "You are a helpful school AI tutor. Keep answers short (2-4 sentences). "
            "Be encouraging, actionable, and avoid policy/legal advice. "
            "If asked about grades, suggest study tactics; if asked about attendance, encourage consistency."
        )
        final_prompt = system + "\n\nStudent context: " + (student_name or "Student") + "\n\nQuestion:\n" + prompt
        resp = self.model.generate_content(final_prompt)
        return (resp.text or "").strip()


def ask_gemini(prompt: str, student_name: Optional[str] = None) -> str:
    client = GeminiClient()
    return client.ask(prompt, student_name=student_name)
