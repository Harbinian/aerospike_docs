# -*- coding: utf-8 -*-
"""AI-powered document cleaning service using LLM (Minimax).

Provides intelligent document cleaning and formatting capabilities:
- Fixes OCR errors and unnatural line breaks
- Reconstructs tables in Markdown format
- Ensures proper heading hierarchy
- Preserves core business data and proper nouns

Architecture:
- LLMDocCleaner: Main service class for document cleaning
"""

import logging
import os
import requests
from pathlib import Path
from typing import Optional

from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.schemas import ServiceResponse

logger = logging.getLogger(__name__)

# API Configuration
MINIMAX_API_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"
API_TIMEOUT = 300  # 5 minutes timeout for long document processing


class LLMDocCleaner:
    """AI-powered document cleaner using Minimax LLM."""

    SYSTEM_PROMPT = """你是一个严谨的航空工业级文档排版专家。请将用户输入的粗糙文本重新排版为标准的 Markdown 格式。

要求：
1. 修复明显的 OCR 错别字和不自然的换行；
2. 如果遇到类似表格的数据，请使用 Markdown 表格重构；
3. 梳理清晰的标题层级 (#, ##)；
4. 绝对不要篡改核心业务数据、数值和专有名词；
5. 只输出 Markdown 内容，不要包含任何多余的解释或寒暄。"""

    def __init__(self, api_config: ApiConfig = None):
        """Initialize the cleaner with config.

        Args:
            api_config: API configuration instance. If None, uses default ApiConfig().
        """
        if api_config is None:
            api_config = ApiConfig()

        self.api_key = api_config.minimax_api_key
        self.model_name = api_config.minimax_model_name

        if not self.api_key:
            raise ValueError("CRITICAL: MINIMAX_API_KEY not configured in .env or environment variables! System refused to start.")

        if not self.model_name:
            raise ValueError("CRITICAL: MINIMAX_MODEL_NAME not configured in .env or environment variables! System refused to start.")

        logger.info(f"LLMDocCleaner initialized with model: {self.model_name}")

    def clean_and_format(self, raw_text: str) -> ServiceResponse[str]:
        """Clean and format raw text using LLM.

        Args:
            raw_text: Raw input text to clean

        Returns:
            ServiceResponse with cleaned markdown text
        """
        if not raw_text or not raw_text.strip():
            return ServiceResponse(
                success=False,
                data="",
                error_msg="Input text is empty"
            )

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": raw_text}
                ],
                "temperature": 0.3,  # Low temperature for consistency
                "max_tokens": 16000
            }

            response = requests.post(
                MINIMAX_API_URL,
                headers=headers,
                json=payload,
                timeout=API_TIMEOUT
            )

            if response.status_code != 200:
                error_msg = f"API error: {response.status_code} - {response.text}"
                logger.error(f"LLMDocCleaner: {error_msg}")
                return ServiceResponse(success=False, data="", error_msg=error_msg)

            result = response.json()

            # Extract content from response
            if "choices" in result and len(result["choices"]) > 0:
                cleaned_text = result["choices"][0]["message"]["content"]

                # Strip markdown code blocks if present
                if cleaned_text.strip().startswith("```"):
                    lines = cleaned_text.split("\n")
                    # Remove opening ```markdown or ```
                    if lines[0].strip().startswith("```"):
                        lines = lines[1:]
                    # Remove closing ```
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    cleaned_text = "\n".join(lines)

                logger.info(f"Successfully cleaned {len(raw_text)} chars -> {len(cleaned_text)} chars")
                return ServiceResponse(success=True, data=cleaned_text, error_msg="")
            else:
                error_msg = "Invalid API response format"
                logger.error(f"LLMDocCleaner: {error_msg}")
                return ServiceResponse(success=False, data="", error_msg=error_msg)

        except requests.Timeout:
            error_msg = "API request timeout"
            logger.error(f"LLMDocCleaner: {error_msg}")
            return ServiceResponse(success=False, data="", error_msg=error_msg)
        except Exception as e:
            error_msg = f"Cleaning failed: {str(e)}"
            logger.error(f"LLMDocCleaner: {error_msg}")
            return ServiceResponse(success=False, data="", error_msg=error_msg)

    def clean_file(self, input_path: Path, output_path: Optional[Path] = None) -> ServiceResponse[str]:
        """Clean a file and optionally save to output path.

        Args:
            input_path: Path to input file
            output_path: Optional path for output (if None, returns cleaned text)

        Returns:
            ServiceResponse with cleaned text or file path
        """
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                raw_text = f.read()

            result = self.clean_and_format(raw_text)

            if result.success and output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result.data)
                logger.info(f"Cleaned file saved to: {output_path}")
                return ServiceResponse(success=True, data=str(output_path), error_msg="")

            return result

        except Exception as e:
            error_msg = f"Failed to clean file: {str(e)}"
            logger.error(f"LLMDocCleaner: {error_msg}")
            return ServiceResponse(success=False, data="", error_msg=error_msg)
