"""Model capability detection based on model name.

Pure Python — no FreeCAD imports. Fully testable in isolation.

Default strategy: models released before 2025 H2 are considered weak.
Only explicitly named strong models (2025 H2+) are exempt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ModelProfile:
    """Runtime behavior profile for a model."""

    use_weak_prompt: bool = True

    @classmethod
    def from_model_name(cls, model_name: str) -> ModelProfile:
        """Heuristic detection from model name.

        Aggressive: all models default to weak unless explicitly recognized
        as strong (2025 H2+ frontier models).
        """
        name_lower = model_name.lower()

        # Explicitly strong models (2025 H2+ frontier)
        strong_patterns = [
            r'gpt-4\.1',
            r'gpt-4o',
            r'o[34](-mini)?',
            r'claude-opus-4', r'claude-sonnet-4',
            r'gemini-2\.5',
            r'deepseek-r2',
            r'glm-5',
            r'qwen-?(?:max|72b|32b)',
            r'kimi-.*k2',
        ]
        for pat in strong_patterns:
            if re.search(pat, name_lower):
                return cls(use_weak_prompt=False)

        # Everything else defaults to weak (use_weak_prompt=True from dataclass default)
        return cls()
