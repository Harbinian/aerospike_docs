# -*- coding: utf-8 -*-
"""
Conversion Service - DDD Domain Service for Document-to-Markdown Pipeline

Provides complete document conversion pipeline:
- Parses DOCX/PDF/Excel documents
- Converts to Markdown with YAML frontmatter
- Handles images and tables (merged cells -> HTML)
- Generates WikiLinks for cross-references

Architecture:
- PipelineConverter: Main orchestrator class
- MarkdownConverter: Converts DocumentElement to Markdown
- MetadataEnhancer: Adds knowledge graph metadata
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict, Any

from aerospike_docs.base import BaseService
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.logging import get_logger

# Import parser from same package
from aerospike_docs.conversion.parser import (
    DocumentElement, ElementType, create_parser, DocumentParserFactory
)

# Try to import image handler
try:
    from scripts.image_handler import ImageHandler
except ImportError:
    ImageHandler = None

# Import utilities
from aerospike_docs.core.utils import clean_text, write_file_with_utf8

logger = get_logger(__name__)


# ============================================================================
# Conversion Result
# ============================================================================

class ConvertResult:
    """Conversion result with detailed status."""

    def __init__(self, success: bool, error: str = "",
                 html_table_count: int = 0, html_fallback_used: bool = False):
        self.success = success
        self.error = error
        self.html_table_count = html_table_count
        self.html_fallback_used = html_fallback_used

    def to_tuple(self) -> Tuple[bool, str, int, bool]:
        """Convert to tuple format."""
        return (self.success, self.error, self.html_table_count, self.html_fallback_used)


# ============================================================================
# Metadata Enhancer
# ============================================================================

class MetadataEnhancer:
    """
    Metadata enhancer - adds knowledge graph support to Markdown.

    Features:
    1. Auto-link references: 《Document Name》 -> [[WikiLinks]]
    2. YAML Frontmatter: Generate structured document metadata
    """

    # Book title pattern
    BOOK_TITLE_PATTERN = re.compile(r'《([^《》]+)》')

    # Default tags
    DEFAULT_TAGS = ["制度"]

    def __init__(self, filename: str = ""):
        """
        Initialize metadata enhancer.

        Args:
            filename: Source filename (for extracting title)
        """
        self.filename = filename
        self.references: Set[str] = set()
        self.headings: List[str] = []

    def extract_references(self, text: str) -> List[str]:
        """Extract book title references from text."""
        matches = self.BOOK_TITLE_PATTERN.findall(text)
        for match in matches:
            normalized = match.strip()
            if normalized:
                self.references.add(normalized)
        return matches

    def wikify_text(self, text: str) -> str:
        """Replace book titles with WikiLinks format."""
        return self.BOOK_TITLE_PATTERN.sub(r'[[\1]]', text)

    def add_heading(self, text: str, level: int):
        """Add heading to structure list (only level 1-3)."""
        if 1 <= level <= 3:
            indent = "  " * (level - 1)
            self.headings.append(f"{indent}- {text}")

    def generate_frontmatter(self, extra_tags: List[str] = None, version: str = None) -> str:
        """Generate YAML Frontmatter."""
        title = os.path.splitext(self.filename)[0] if self.filename else "Untitled"

        tags = self.DEFAULT_TAGS.copy()
        if extra_tags:
            tags.extend(extra_tags)
        tags = list(set(tags))

        ref_list = sorted(self.references)
        structure = self.headings

        lines = ["---"]
        lines.append(f"title: {title}")

        if version and version != "未知":
            lines.append(f"version: \"{version}\"")

        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")

        if ref_list:
            lines.append("references:")
            for ref in ref_list:
                lines.append(f"  - {ref}")
        else:
            lines.append("references: []")

        if structure:
            lines.append("structure:")
            for item in structure:
                lines.append(f"  {item}")
        else:
            lines.append("structure: []")

        lines.append("---\n")
        return "\n".join(lines)


# ============================================================================
# Markdown Converter
# ============================================================================

class MarkdownConverter:
    """Markdown format converter."""

    def __init__(self, image_handler=None,
                 enable_metadata_enhance: bool = True,
                 doc_name: str = None, asset_output_dir: str = None,
                 version: str = None):
        """
        Initialize converter.

        Args:
            image_handler: Image handler instance
            enable_metadata_enhance: Enable WikiLinks + YAML Frontmatter
            doc_name: Resource naming and document name (for Bundle)
            asset_output_dir: Asset output directory (absolute path)
            version: Document version (from header)
        """
        self.image_handler = image_handler
        self.enable_metadata_enhance = enable_metadata_enhance
        self.doc_name = doc_name
        self.asset_output_dir = asset_output_dir
        self.version = version
        self._image_seq = 0

        if image_handler and doc_name and asset_output_dir:
            image_handler.set_context(doc_name, asset_output_dir)

    def _generate_semantic_filename(self, element: DocumentElement) -> str:
        """Generate semantic image filename."""
        import time

        self._image_seq += 1
        context = element.context_text or "img"
        context = re.sub(r'[<>:"/\\|?*\s]', '', context)[:20]
        para_idx = f"{element.para_index:03d}" if element.para_index else "000"
        seq = f"{self._image_seq:02d}"
        doc_prefix = self.doc_name if self.doc_name else "doc"
        return f"{doc_prefix}_p{para_idx}_{seq}_{context}.png"

    def _copy_image_to_assets(self, src_path: str, dst_filename: str) -> str:
        """Copy image to assets directory."""
        if not self.asset_output_dir:
            return os.path.basename(src_path)

        dst_path = os.path.join(self.asset_output_dir, dst_filename)
        parent_dir = os.path.dirname(dst_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        if os.path.exists(dst_path):
            if os.path.isdir(dst_path):
                shutil.rmtree(dst_path)
            elif os.path.isfile(dst_path):
                os.remove(dst_path)

        try:
            with open(src_path, 'rb') as fsrc:
                with open(dst_path, 'wb') as fdst:
                    fdst.write(fsrc.read())
            return f"assets/{dst_filename}"
        except Exception as e:
            logger.warning(f"Copy image failed: {e}")
            return os.path.basename(src_path)

    def convert(self, elements: List[DocumentElement],
                source_path: str, output_path: str,
                doc_name: str = None, asset_output_dir: str = None) -> ConvertResult:
        """Convert DocumentElement list to Markdown."""
        markdown_lines = []
        context = os.path.basename(source_path)

        if doc_name and asset_output_dir and self.image_handler:
            self.image_handler.set_context(doc_name, asset_output_dir)

        html_table_count = 0
        html_fallback_used = False

        filename = os.path.basename(source_path)
        enhancer = MetadataEnhancer(filename) if self.enable_metadata_enhance else None

        # First pass: extract references and heading structure
        if enhancer:
            for element in elements:
                if element.type == ElementType.HEADING:
                    enhancer.add_heading(element.content, element.level)
                    enhancer.extract_references(element.content)
                elif element.type == ElementType.PARAGRAPH:
                    enhancer.extract_references(element.content)
                elif element.type == ElementType.TABLE:
                    enhancer.extract_references(element.content)

        # Generate YAML Frontmatter
        if enhancer:
            markdown_lines.append(enhancer.generate_frontmatter(version=self.version))

        # Document title
        markdown_lines.append(f"# {os.path.splitext(filename)[0]}")
        markdown_lines.append("")
        markdown_lines.append(f"<!-- Auto-generated by PipelineConverter -->")
        markdown_lines.append(f"<!-- Source: {filename} -->")
        markdown_lines.append("")

        for element in elements:
            try:
                converted = self._convert_element(element, context, enhancer)
                if converted:
                    markdown_lines.append(converted)

                if element.type == ElementType.TABLE and element.has_merged_cells:
                    html_table_count += 1
                    html_fallback_used = True
            except Exception as e:
                logger.warning(f"Convert element failed: {e}")
                markdown_lines.append(f"<!-- Convert error: {e} -->")

        markdown_content = "\n".join(markdown_lines)

        if write_file_with_utf8(output_path, markdown_content):
            return ConvertResult(
                success=True,
                error="",
                html_table_count=html_table_count,
                html_fallback_used=html_fallback_used
            )
        else:
            return ConvertResult(
                success=False,
                error="File write failed",
                html_table_count=html_table_count,
                html_fallback_used=html_fallback_used
            )

    def _convert_element(self, element: DocumentElement,
                         context: str, enhancer: MetadataEnhancer = None) -> Optional[str]:
        """Convert single element."""
        if element.type == ElementType.HEADING:
            return self._convert_heading(element, enhancer)
        elif element.type == ElementType.PARAGRAPH:
            return self._convert_paragraph(element, enhancer)
        elif element.type == ElementType.LIST_ITEM:
            return self._convert_list_item(element, enhancer)
        elif element.type == ElementType.TABLE:
            return self._convert_table(element, enhancer)
        elif element.type == ElementType.IMAGE:
            return self._convert_image(element, context, enhancer)
        elif element.type == ElementType.UNKNOWN:
            return self._convert_unknown(element, enhancer)
        return None

    def _convert_heading(self, element: DocumentElement, enhancer: MetadataEnhancer = None) -> str:
        """Convert heading element."""
        level = min(element.level, 6)
        marker = "#" * level
        content = clean_text(element.content)
        if enhancer:
            content = enhancer.wikify_text(content)
        return f"\n{marker} {content}\n"

    def _convert_paragraph(self, element: DocumentElement, enhancer: MetadataEnhancer = None) -> str:
        """Convert paragraph element."""
        content = clean_text(element.content)
        if not content:
            return ""
        if enhancer:
            content = enhancer.wikify_text(content)
        return f"{content}\n"

    def _convert_list_item(self, element: DocumentElement, enhancer: MetadataEnhancer = None) -> str:
        """Convert list item element."""
        content = clean_text(element.content)
        if enhancer:
            content = enhancer.wikify_text(content)
        return f"- {content}"

    def _convert_table(self, element: DocumentElement, enhancer: MetadataEnhancer = None) -> str:
        """Convert table element."""
        if element.type != ElementType.TABLE or not element.content:
            return ""

        raw_data = element.raw_data or {}
        is_word_table = "table" in raw_data

        if is_word_table and element.has_merged_cells:
            return self._wrap_html_table(element.content)

        if element.has_merged_cells or element.content.strip().startswith('<table'):
            return self._wrap_html_table(element.content)
        else:
            content = element.content
            if enhancer:
                content = enhancer.wikify_text(content)
            return f"\n{content}\n"

    def _wrap_html_table(self, html_content: str) -> str:
        """Wrap HTML table in Markdown code block."""
        return f"\n```html\n{html_content}\n```\n"

    def _convert_image(self, element: DocumentElement,
                       context: str, enhancer: MetadataEnhancer = None) -> str:
        """Convert image element."""
        if not element.image_path or not os.path.exists(element.image_path):
            return f"<!-- Image missing: {element.content} -->\n"

        semantic_filename = self._generate_semantic_filename(element)
        relative_path = self._copy_image_to_assets(element.image_path, semantic_filename)

        seq_num = self._image_seq
        context_desc = element.context_text or element.content or "Image"

        return f"\n![Figure {seq_num}: {context_desc}]({relative_path})\n"

    def _convert_unknown(self, element: DocumentElement, enhancer: MetadataEnhancer = None) -> str:
        """Convert unknown element."""
        content = clean_text(element.content)
        if content:
            return f"<!-- {content} -->\n"
        return ""


# ============================================================================
# Pipeline Converter (Main Orchestrator)
# ============================================================================

class PipelineConverter:
    """
    Pipeline Converter - Main orchestrator for document conversion.

    Coordinates parsing, conversion, and output generation.
    Supports batch conversion with incremental processing.
    """

    DEFAULT_EXTENSIONS = (".docx", ".doc", ".pdf", ".xlsx", ".xls")

    def __init__(self, image_handler=None, mcp_available: bool = False):
        """
        Initialize pipeline converter.

        Args:
            image_handler: Image handler instance
            mcp_available: Whether MCP is available for image analysis
        """
        self.converter = MarkdownConverter(image_handler)
        self.image_handler = image_handler
        self.mcp_available = mcp_available

    def convert_file(self, source_path: str, output_dir: str,
                    doc_name: str = None, version: str = None) -> ConvertResult:
        """
        Convert single file.

        Args:
            source_path: Source file path
            output_dir: Output directory
            doc_name: Document name (optional)
            version: Document version (optional)

        Returns:
            ConvertResult
        """
        source_path = Path(source_path)
        output_dir = Path(output_dir)

        # Determine doc_name
        if not doc_name:
            doc_name = source_path.stem

        # Create output structure (Page Bundle)
        doc_bundle_dir = output_dir / doc_name
        assets_dir = doc_bundle_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        output_md = doc_bundle_dir / f"{doc_name}.md"

        # Parse document
        try:
            parser = create_parser(str(source_path))
            elements = parser.parse(str(source_path))
        except Exception as e:
            return ConvertResult(success=False, error=f"Parse failed: {e}")

        if not elements:
            return ConvertResult(success=False, error="Empty document")

        # Convert
        converter = MarkdownConverter(
            self.image_handler,
            doc_name=doc_name,
            asset_output_dir=str(assets_dir),
            version=version
        )

        return converter.convert(
            elements,
            str(source_path),
            str(output_md),
            doc_name=doc_name,
            asset_output_dir=str(assets_dir)
        )

    def convert_folder(self, source_folder: str, target_folder: str,
                      formats: tuple = None, force: bool = False) -> Dict[str, Any]:
        """
        Batch convert folder.

        Args:
            source_folder: Source folder path
            target_folder: Target folder path
            formats: File extensions to process
            force: Force full rebuild (ignore incremental)

        Returns:
            Conversion results summary
        """
        source_path = Path(source_folder)
        target_path = Path(target_folder)

        if not formats:
            formats = self.DEFAULT_EXTENSIONS

        # Collect files
        doc_files = [
            f for f in source_path.rglob("*")
            if f.is_file() and f.suffix.lower() in formats
        ]

        results = {
            "success": [],
            "failed": [],
            "skipped": [],
            "total": len(doc_files)
        }

        for doc_file in doc_files:
            # Check incremental
            output_md = target_path / doc_file.stem / f"{doc_file.stem}.md"
            if not force and output_md.exists():
                if doc_file.stat().st_mtime <= output_md.stat().st_mtime:
                    results["skipped"].append(doc_file.name)
                    continue

            # Convert
            result = self.convert_file(str(doc_file), str(target_folder))

            if result.success:
                results["success"].append(doc_file.name)
            else:
                results["failed"].append((doc_file.name, result.error))

        return results


# ============================================================================
# Conversion Service (Legacy - Subprocess Based)
# ============================================================================

class ConversionService(BaseService):
    """Legacy service for document conversion operations (subprocess-based).

    Note: For direct Python API, use PipelineConverter instead.
    """

    def __init__(self, api_config: ApiConfig, scripts_dir: Path = None,
                 script_name: str = "convert_docs.py", timeout: int = 300,
                 reports_dir: Path = None):
        """Initialize ConversionService.

        Args:
            api_config: API configuration instance
            scripts_dir: Directory containing conversion scripts
            script_name: Name of the conversion script
            timeout: Subprocess timeout in seconds
            reports_dir: Directory for conversion reports
        """
        super().__init__(api_config)
        self._scripts_dir = scripts_dir or Path(__file__).parent.parent
        self._script_name = script_name
        self._timeout = timeout
        self._reports_dir = reports_dir or Path(__file__).parent.parent / "reports"

    def execute(self, source_dir: str, target_dir: str, **kwargs) -> Dict[str, Any]:
        """Execute document conversion.

        Args:
            source_dir: Source directory containing DOCX/PDF files
            target_dir: Target directory for Markdown output
            **kwargs: Additional options (timeout, etc.)

        Returns:
            Dict containing success status and any error message
        """
        self._logger.info(f"Starting conversion: {source_dir} -> {target_dir}")

        try:
            # Validate paths
            source_path = Path(source_dir)
            target_path = Path(target_dir)

            if not source_path.exists():
                return {"success": False, "error": f"Source directory does not exist: {source_dir}"}

            target_path.mkdir(parents=True, exist_ok=True)

            # Run conversion script
            result = self._run_conversion_script(source_dir, target_dir, **kwargs)

            if result.returncode == 0:
                self._logger.info("Conversion completed successfully")
                return {"success": True, "message": "Conversion completed successfully"}
            else:
                error_msg = result.stderr or "Unknown error during conversion"
                self._logger.error(f"Conversion failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except FileNotFoundError as e:
            self._logger.error(f"File not found: {e}")
            return {"success": False, "error": f"File not found: {e}"}
        except PermissionError as e:
            self._logger.error(f"Permission denied: {e}")
            return {"success": False, "error": f"Permission denied: {e}"}
        except subprocess.TimeoutExpired as e:
            self._logger.error(f"Conversion timed out: {e}")
            return {"success": False, "error": f"Timeout expired: {e}"}
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"OS error during conversion: {e}")
            return {"success": False, "error": f"File system error: {e}"}
        except (ValueError, TypeError, KeyError) as e:
            self._logger.exception("Conversion failed: invalid data")
            return {"success": False, "error": f"Invalid data: {e}"}

    def _run_conversion_script(self, source_dir: str, target_dir: str, **kwargs) -> subprocess.CompletedProcess:
        """Run the conversion script as subprocess.

        Args:
            source_dir: Source directory path
            target_dir: Target directory path
            **kwargs: Additional arguments

        Returns:
            CompletedProcess result
        """
        script_path = self._scripts_dir / self._script_name

        cmd = [sys.executable, str(script_path), source_dir, target_dir]

        timeout = kwargs.get("timeout", self._timeout)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=self._scripts_dir
        )

        return result

    def validate(self, source_dir: str = None, target_dir: str = None, **kwargs) -> bool:
        """Validate conversion parameters.

        Args:
            source_dir: Source directory path
            target_dir: Target directory path
            **kwargs: Additional parameters

        Returns:
            True if valid, False otherwise
        """
        if source_dir is None or target_dir is None:
            return False

        # Path security check - prevent directory traversal
        source_path = Path(source_dir).resolve()
        target_path = Path(target_dir).resolve()

        # Ensure paths don't escape the project root
        root_dir = self._scripts_dir.resolve()

        try:
            source_path.relative_to(root_dir)
            target_path.relative_to(root_dir)
        except ValueError:
            self._logger.warning(f"Path validation failed: paths outside root directory")
            return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """Get current conversion status from report file.

        Returns:
            Dict containing conversion statistics
        """
        report_file = self._reports_dir / "conversion_report.csv"

        if not report_file.exists():
            return {"total": 0, "success": 0, "failed": 0, "partial": 0}

        try:
            import pandas as pd

            df = pd.read_csv(report_file, encoding="utf-8")

            total = len(df)
            success = len(df[df['Status'].str.lower() == 'success'])
            failed = len(df[df['Status'].str.lower() == 'failed'])
            partial = len(df[df['Status'].str.lower() == 'partial'])

            return {
                "total": total,
                "success": success,
                "failed": failed,
                "partial": partial,
                "html_fallback": int(df.get('HTML_Fallback', pd.Series([0] * total)).sum())
            }
        except Exception as e:
            self._logger.warning(f"Failed to read conversion report: {e}")
            return {"total": 0, "success": 0, "failed": 0, "partial": 0}
