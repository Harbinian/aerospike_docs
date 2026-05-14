# -*- coding: utf-8 -*-
"""Mining service for terminology discovery using LLM."""

import gc
import json
import re
import os
import subprocess
import sys
import time
import threading
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator, Set
from datetime import datetime

from aerospike_docs.base import BaseService
from aerospike_docs.core.config import ApiConfig, MINIMAX_MODEL_NAME
from aerospike_docs.core.logging import get_logger

# ============================================================================
# API Configuration
# ============================================================================
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_API_URL = os.environ.get(
    "MINIMAX_API_URL",
    "https://api.minimax.chat/v1/text/chatcompletion_v2"
)
# Model name loaded from environment via core.config (12-Factor pattern)
API_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY = 2
RETRY_BACKOFF_FACTOR = 2
RATE_LIMIT_SEMAPHORE = 10

# Try to import MCP module
try:
    from mcp__MiniMax__understand_image import mcp__MiniMax__understand_image
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Try to import domain config
try:
    import domain_config
    DOMAIN_CONFIG_AVAILABLE = True
except ImportError:
    DOMAIN_CONFIG_AVAILABLE = False

# Rate limiter
rate_limiter = threading.Semaphore(RATE_LIMIT_SEMAPHORE)

# Logger
logger = get_logger(__name__)

# ============================================================================
# Prompt Templates
# ============================================================================
TERM_PROMPT = """你是一位航空制造领域的数据治理专家。

领域背景：
{domain_context}

请分析以下文档片段，提取其中的专业术语和同义词变体。

## 重要约束
1. 只提取与{domain_keywords}相关的**专业术语**
2. 如果无法确定术语，**必须返回空数组**
3. 忽略通用管理用语、流程描述、无关内容

## 【极其重要】实体提取边界规则
在提取实体、角色、部门名称时，**绝不允许丢失组织前缀、项目名称或制造商定语**！
- 例如：必须完整提取"客户乙工装管理人员"，严禁将其截断为"工装管理人员"
- 例如：必须完整提取"客户甲质量审核员"，严禁将其截断为"质量审核员"
- 例如：必须完整提取"复合材料铺贴工"，严禁将其截断为"铺贴工"
保持原文特有的业务属性词组完整。

## 【实体消歧强制规则】
遇到通用角色或岗位（如管理员、安全员、技术员等）时，你绝对不能只输出孤立的短名称！你必须根据当前文档的【发文部门】、【标题】或【上下文段落】，推断该角色所属的业务域，并强制使用『部门名称-角色名称』的格式进行输出（例如：将孤立的'管理员'提取为'制造部-管理员'或'质量部-管理员'）。只有在原文明确包含完整全称时，才直接使用原文全称。

## 输出格式要求（必须包含出处溯源）
{{"doc_focus": "文档核心主题", "terms": [{{"term": "标准术语", "definition": "定义", "synonyms": "同义词1;同义词2", "category": "类别", "confidence": 0.95, "source_doc": "当前解析的文件名", "evidence": "原文中的原话片段"}}]}}

注意：
- confidence 必须是 0.0-1.0 之间的浮点数，表示术语可信度
- source_doc 必须填写当前解析的文件名
- evidence 必须填写原文中的原话片段（不超过50字）

仅返回 JSON，不要有其他内容。

文档内容：
{content}
"""

DOMAIN_KEYWORDS = "航空制造、客户甲飞机、ACFT_B/ACFT_A、工装模具、质量管理、复合材料、特种工艺"

# ============================================================================
# Utility Functions
# ============================================================================

def retry_with_backoff(attempt: int, base_delay: int = RETRY_DELAY) -> int:
    """Calculate exponential backoff delay."""
    return base_delay * (RETRY_BACKOFF_FACTOR ** attempt)


def build_term_prompt(domain_context: str, content: str, filename: str, chunk_size: int = 8000) -> str:
    """Build term mining prompt."""
    return TERM_PROMPT.format(
        domain_context=domain_context or "航空制造领域",
        domain_keywords=DOMAIN_KEYWORDS,
        content=f"=== {filename} ===\n{content[:chunk_size]}"
    )


def safe_mcp_call(prompt: str, timeout: int = API_TIMEOUT) -> Optional[str]:
    """Safe API call with timeout and rate limiting."""
    if not MCP_AVAILABLE and not MINIMAX_API_KEY:
        return None

    rate_limiter.acquire()
    try:
        if MCP_AVAILABLE:
            try:
                import threading
                import ctypes

                result = [None]
                exception = [None]
                thread_done = [False]

                def call_api():
                    try:
                        result[0] = mcp__MiniMax__understand_image(
                            image_source="",
                            prompt=prompt
                        )
                    except Exception as e:
                        exception[0] = e
                    finally:
                        thread_done[0] = True

                thread = threading.Thread(target=call_api)
                thread.daemon = True
                thread.start()
                thread.join(timeout)

                if not thread_done[0]:
                    return None

                if exception[0]:
                    raise exception[0]

                return result[0]

            except Exception as e:
                pass

        if MINIMAX_API_KEY:
            return call_minimax_api(prompt, timeout + 30)

        return None
    finally:
        rate_limiter.release()


def call_minimax_api(prompt: str, timeout: int = 30) -> Optional[str]:
    """Direct Minimax API call with rate limiting."""
    if not MINIMAX_API_KEY:
        return None

    rate_limiter.acquire()
    try:
        try:
            import requests

            headers = {
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": MINIMAX_MODEL_NAME,
                "messages": [
                    {"role": "system", "content": "你是一位航空制造领域的资深数据治理专家。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 2048
            }

            response = requests.post(
                MINIMAX_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    return result["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"Minimax API call failed: {e}")

        return None
    finally:
        rate_limiter.release()


def parse_llm_response(result: str) -> tuple:
    """Parse LLM JSON response with anti-hallucination validation.

    CRITICAL: This function implements strict validation to prevent
    hallucinated data from being accepted.

    Returns:
        Tuple of (doc_focus, terms_list) or (None, None) on failure
    """
    try:
        # Clean markdown code blocks
        cleaned = re.sub(r'^```json\s*', '', result.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned)

        # Try parsing new format
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            json_obj = json.loads(json_match.group(0))
            if 'terms' in json_obj:
                doc_focus = json_obj.get('doc_focus', '')
                terms = json_obj['terms']

                # Anti-hallucination: Validate each term has required fields
                validated_terms = []
                for term in terms:
                    # Must have term name and evidence
                    if term.get('term') and term.get('evidence'):
                        validated_terms.append(term)

                return doc_focus, validated_terms

        # Fallback to old format
        json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if json_match:
            terms = json.loads(json_match.group(0))
            # Filter with validation
            validated_terms = [t for t in terms if t.get('term') and t.get('evidence')]
            return None, validated_terms

    except json.JSONDecodeError:
        pass

    return None, None


def get_memory_mb() -> float:
    """Get current memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except:
        return 0


# ============================================================================
# TermMiner Domain Service
# ============================================================================

class TermMiner:
    """Domain Service for LLM-powered terminology mining.

    Extracts core mining logic from StreamTermMiner for better testability
    and reuse. Maintains anti-hallucination validation.
    """

    def __init__(self, docs_dir: str = "docs", output_file: str = "term_candidates.csv",
                 output_format: str = "csv", resume: bool = False,
                 chunk_size: int = 8000, chunk_overlap: int = 1000,
                 max_retries: int = MAX_RETRIES):
        """Initialize TermMiner.

        Args:
            docs_dir: Directory containing documents to mine
            output_file: Output file path
            output_format: 'csv' or 'yaml'
            resume: Enable checkpoint resume
            chunk_size: Text chunk size for LLM
            chunk_overlap: Overlap between chunks
            max_retries: Max API retry attempts
        """
        self.docs_dir = Path(docs_dir)
        self.output_file = output_file
        self.output_format = output_format.lower()
        self.mcp_available = MCP_AVAILABLE
        self.resume = resume
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_retries = max_retries
        self.processed_files: Set[str] = set()

        # Term deduplication tracking
        self.seen_terms: Set[str] = set()
        self.term_records: Dict[str, Dict] = {}

        # CSV field names
        self.fieldnames = [
            'Recommended_ID', 'Term', 'Definition', 'Detected_Variants',
            'Frequency', 'Source_Doc', 'Evidence', 'Category',
            'AI_Note', 'AI_Reasoning', 'Doc_Focus', 'Review_Status'
        ]

        # YAML structure
        self.yaml_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'source_directory': str(Path(docs_dir).absolute()),
                'total_files': 0,
                'extraction_version': 'v2_namespace'  # D5-3: Version tracking
            },
            'entities': []
        }

        # Checkpoint file
        self.processed_log = ".term_mining_processed.json"
        self.failed_log = "term_mining_failed.log"

    def scan_files(self) -> List[str]:
        """Scan for Markdown files."""
        md_files = []
        for f in self.docs_dir.rglob("*.md"):
            path_str = str(f)
            if '/concepts/' not in path_str and '/transformation/' not in path_str:
                md_files.append(path_str)
        return md_files

    def read_content(self, filepath: str) -> str:
        """Read and clean file content."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Remove Frontmatter
        content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        # Remove code blocks
        content = re.sub(r'```[\s\S]*?```', '', content)
        content = re.sub(r'`[^`]+`', '', content)

        return content.strip()

    def _chunk_content(self, content: str) -> Generator[str, None, None]:
        """Generate content chunks."""
        if len(content) <= self.chunk_size:
            yield content
            return

        start = 0
        while start < len(content):
            end = min(start + self.chunk_size, len(content))
            yield content[start:end]
            start = end - self.chunk_overlap

    def normalize_term(self, term: str) -> str:
        """Normalize term for deduplication."""
        if not term:
            return ""
        normalized = term.lower()
        normalized = re.sub(r'[\s\-_.,;:!?\'"()（）【】《》]', '', normalized)
        return normalized

    def _extract_terms(self, content: str, filename: str, chunk_idx: int) -> tuple:
        """Extract terms via LLM with anti-hallucination validation."""
        domain_context = domain_config.DOMAIN_CONTEXT if DOMAIN_CONFIG_AVAILABLE else ""
        prompt = build_term_prompt(domain_context, content, filename, self.chunk_size)

        last_error = None

        for attempt in range(self.max_retries):
            try:
                result = safe_mcp_call(prompt)

                if result is None:
                    last_error = "API returned empty"
                    backoff_delay = retry_with_backoff(attempt)
                    time.sleep(backoff_delay)
                    continue

                doc_focus, terms = parse_llm_response(result)

                if terms:
                    return doc_focus, terms

                last_error = "Cannot parse result"

            except Exception as e:
                last_error = str(e)
                backoff_delay = retry_with_backoff(attempt)
                time.sleep(backoff_delay)

        return None, None

    def process_file(self, filepath: str) -> tuple:
        """Process single file and collect terms.

        Returns:
            (success: bool, doc_focus: str)
        """
        filename = Path(filepath).stem
        content = self.read_content(filepath)

        if not content:
            return False, ""

        # Process first 2 chunks only
        for chunk_idx, chunk in enumerate(self._chunk_content(content)):
            if chunk_idx >= 2:
                break

            doc_focus, terms = self._extract_terms(chunk, filename, chunk_idx)

            if terms:
                for item in terms:
                    self._write_term(item, filepath, doc_focus)

            del terms
            del chunk
            gc.collect()

        return True, doc_focus if 'doc_focus' in locals() else ""

    def _write_term(self, item: Dict, source_file: str, doc_focus: str):
        """Write term with deduplication."""
        term = item.get('term', '').strip()
        if not term:
            return

        normalized = self.normalize_term(term)

        if normalized in self.seen_terms:
            # Merge with existing
            existing = self.term_records[normalized]

            # Merge variants
            existing_variants = set(existing.get('variants', []))
            synonyms = item.get('synonyms', '')
            if synonyms:
                for s in re.split(r'[;；]', str(synonyms)):
                    s = s.strip()
                    if s and self.normalize_term(s) != normalized:
                        existing_variants.add(s)
            existing['variants'] = list(existing_variants)

            # Merge sources
            existing_sources = set(existing.get('sources', []))
            existing_sources.add(source_file)
            existing['sources'] = list(existing_sources)

            # Update frequency
            existing['frequency'] = existing.get('frequency', 1) + 1

        else:
            # New term
            variants = [term]
            synonyms = item.get('synonyms', '')
            if synonyms:
                for s in re.split(r'[;；]', str(synonyms)):
                    s = s.strip()
                    if s and self.normalize_term(s) != normalized:
                        variants.append(s)

            self.seen_terms.add(normalized)
            self.term_records[normalized] = {
                'term': term,
                'definition': item.get('definition', '').strip(),
                'variants': variants,
                'sources': [source_file],
                'source_doc': item.get('source_doc', '').strip(),
                'evidence': item.get('evidence', '').strip(),
                'category': item.get('category', ''),
                'reasoning': item.get('reasoning', ''),
                'doc_focus': doc_focus,
                'frequency': 1
            }

    def flush_to_output(self) -> int:
        """Write accumulated terms to output file.

        Returns:
            Number of terms written
        """
        if not self.term_records:
            return 0

        if self.output_format == 'yaml':
            for normalized, record in self.term_records.items():
                entity = {
                    'id': '',
                    'name': record['term'],
                    'aliases': record['variants'][1:] if len(record['variants']) > 1 else [],
                    'en_term': '',
                    'description': record.get('definition', record.get('reasoning', '')),
                    'category': record.get('category', ''),
                    'source_file': '; '.join(record['sources']),
                    'source_doc': record.get('source_doc', ''),
                    'evidence': record.get('evidence', ''),
                    'review_status': 'pending',
                    'ai_note': f'Mined - {datetime.now().strftime("%Y-%m-%d")}'
                }
                self.yaml_data['entities'].append(entity)
        else:
            import csv
            with open(self.output_file, 'w', newline='', encoding='utf-8-sig') as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=self.fieldnames)
                writer.writeheader()

                for normalized, record in self.term_records.items():
                    writer.writerow({
                        'Recommended_ID': '',
                        'Term': record.get('term', ''),
                        'Definition': record.get('definition', ''),
                        'Detected_Variants': '; '.join(record['variants'][:10]),
                        'Frequency': record.get('frequency', 1),
                        'Source_Doc': record.get('source_doc', ''),
                        'Evidence': record.get('evidence', ''),
                        'Category': record.get('category', ''),
                        'AI_Note': f'流式挖掘 - {datetime.now().strftime("%Y-%m-%d")}',
                        'AI_Reasoning': record.get('reasoning', ''),
                        'Doc_Focus': record.get('doc_focus', ''),
                        'Review_Status': 'pending'
                    })

        return len(self.term_records)

    def load_processed_files(self) -> Set[str]:
        """Load checkpoint for resume."""
        processed = set()
        if os.path.exists(self.processed_log):
            try:
                with open(self.processed_log, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    processed = set(data.get('processed_files', []))
            except Exception as e:
                logger.warning(f"Failed to load processed files checkpoint: {e}")
        return processed

    def save_processed_file(self, filepath: str):
        """Save checkpoint."""
        self.processed_files.add(filepath)
        try:
            with open(self.processed_log, 'w', encoding='utf-8') as f:
                json.dump({
                    'processed_files': list(self.processed_files),
                    'last_updated': datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save processed files checkpoint: {e}")

    def log_failed(self, filepath: str, error: str):
        """Log failed file."""
        with open(self.failed_log, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} | {filepath} | {error}\n")

    def mine(self) -> int:
        """Execute term mining.

        Returns:
            Number of files processed
        """
        print("\n" + "=" * 60)
        print("            TermMiner - Domain Service")
        print("=" * 60)

        if not MCP_AVAILABLE and not MINIMAX_API_KEY:
            print("[ERROR] MCP or MINIMAX_API_KEY not configured")
            return 0

        files = self.scan_files()
        if not files:
            print("[ERROR] No Markdown files found")
            return 0

        # Resume from checkpoint
        if self.resume:
            self.processed_files = self.load_processed_files()
            files = [f for f in files if f not in self.processed_files]

        print(f"\n[1/2] Found {len(files)} files to process")
        print(f"[Format] Output: {self.output_format.upper()}\n")

        processed = 0
        failed = 0
        total_terms = 0

        try:
            for filepath in files:
                processed += 1
                filename = Path(filepath).stem

                print(f"PROGRESS:{processed}/{len(files)}|{filename}|terms:{total_terms}", flush=True)

                try:
                    success, doc_focus = self.process_file(filepath)

                    if not success:
                        failed += 1
                        self.log_failed(filepath, "Processing failed")
                    else:
                        self.save_processed_file(filepath)
                        prev_count = total_terms
                        total_terms = len(self.term_records)
                        if total_terms > prev_count:
                            print(f"    [+{total_terms - prev_count}] terms, total {total_terms}")

                except Exception as e:
                    failed += 1
                    self.log_failed(filepath, str(e))

        finally:
            pass

        print(f"\n[Complete] Processed {processed} files, failed {failed}")
        print(f"[Stats] Mined {total_terms} unique terms")

        # Flush to output
        written_count = self.flush_to_output()

        if self.output_format == 'yaml':
            yaml_path = self.output_file if self.output_file.endswith('.yaml') else self.output_file.replace('.csv', '.yaml')
            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.yaml_data, f, allow_unicode=True, sort_keys=False)
            print(f"\n[Result] Terms: {yaml_path}")
        else:
            print(f"\n[Result] Terms: {self.output_file} ({written_count} records)")

        return processed


class MiningService(BaseService):
    """Service for mining terminology from documents using LLM.

    Uses Minimax API for AI-powered term extraction from aerospace
    manufacturing documentation.
    """

    def __init__(self, api_config: ApiConfig, scripts_dir: Path, timeout: int = 300, default_docs_dir: str = "./outputs"):
        super().__init__(api_config)
        self.scripts_dir = scripts_dir
        self.timeout = timeout
        self.default_docs_dir = default_docs_dir
        self._script_name = "mine_terms.py"

    def execute(self, docs_dir: str = None, **kwargs) -> Dict[str, Any]:
        """Execute terminology mining.

        Args:
            docs_dir: Directory containing documents to mine from
            **kwargs: Additional options (model, max_terms, etc.)

        Returns:
            Dict containing mining results
        """
        self._logger.info(f"Starting terminology mining from {docs_dir}")

        try:
            # Validate docs directory
            if docs_dir is None:
                docs_dir = self.default_docs_dir

            docs_path = Path(docs_dir)
            if not docs_path.exists():
                return {"success": False, "error": f"Documents directory does not exist: {docs_dir}"}

            # Run mining script
            result = self._run_mining_script(docs_dir, **kwargs)

            if result.returncode == 0:
                self._logger.info("Mining completed successfully")
                return {"success": True, "message": "Terminology mining completed"}
            else:
                error_msg = result.stderr or "Unknown error during mining"
                self._logger.error(f"Mining failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except subprocess.TimeoutExpired as e:
            self._logger.error(f"Mining timed out: {e}")
            return {"success": False, "error": f"Timeout expired: {e}"}
        except FileNotFoundError as e:
            self._logger.error(f"Script not found: {e}")
            return {"success": False, "error": f"Script not found: {e}"}
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"OS error during mining: {e}")
            return {"success": False, "error": f"File system error: {e}"}
        except (ValueError, TypeError, KeyError) as e:
            self._logger.exception("Mining failed: invalid data")
            return {"success": False, "error": f"Invalid data: {e}"}

    def _run_mining_script(self, docs_dir: str, **kwargs) -> subprocess.CompletedProcess:
        """Run the mining script as subprocess.

        Args:
            docs_dir: Documents directory path
            **kwargs: Additional arguments

        Returns:
            CompletedProcess result
        """
        script_path = self.scripts_dir / self._script_name

        cmd = [sys.executable, str(script_path), "--docs", docs_dir]

        # Add optional parameters
        if kwargs.get("model"):
            cmd.extend(["--model", kwargs["model"]])

        if kwargs.get("max_terms"):
            cmd.extend(["--max-terms", str(kwargs["max_terms"])])

        # Check for API key in environment
        api_key = os.environ.get("MINIMAX_API_KEY")

        timeout = kwargs.get("timeout", self.timeout)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=self.scripts_dir.parent,
            env={**os.environ, "MINIMAX_API_KEY": api_key or ""} if api_key else None
        )

        return result

    def validate(self, docs_dir: str = None, **kwargs) -> bool:
        """Validate mining parameters.

        Args:
            docs_dir: Documents directory path
            **kwargs: Additional parameters

        Returns:
            True if valid, False otherwise
        """
        if docs_dir is None:
            return True  # Will use default

        # Path security check
        docs_path = Path(docs_dir).resolve()
        root_dir = self.scripts_dir.parent.resolve()

        try:
            docs_path.relative_to(root_dir)
        except ValueError:
            self._logger.warning(f"Path validation failed: {docs_dir} is outside root")
            return False

        return True

    def get_candidates(self) -> List[Dict[str, Any]]:
        """Get mined term candidates.

        Returns:
            List of term candidates
        """
        candidates_file = self.scripts_dir.parent / "term_candidates.yaml"

        if not candidates_file.exists():
            return []

        try:
            with open(candidates_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get("terms", []) if data else []
        except yaml.YAMLError as e:
            self._logger.warning(f"Failed to parse candidates (invalid YAML): {e}")
            return []
        except OSError as e:
            self._logger.warning(f"Failed to read candidates: {e}")
            return []
