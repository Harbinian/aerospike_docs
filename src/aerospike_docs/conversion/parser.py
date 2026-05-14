# -*- coding: utf-8 -*-
"""
Document Parser Service - DDD Domain Service for Document Parsing

Provides unified document parsing for multiple formats:
- .docx: Using python-docx
- .doc: Using win32com (Windows only)
- .pdf: Using pdfplumber
- .xlsx: Using pandas/openpyxl

Architecture: Follows DDD pattern with factory registration.
"""

import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum

# Common parser dependencies
from docx import Document
from docx.document import Document as DocDocument
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table
from docx.text.paragraph import Paragraph

from aerospike_docs.core.utils import clean_text
from aerospike_docs.core.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class ElementType(Enum):
    """Document element types - unified format."""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
    LIST_ITEM = "list_item"
    UNKNOWN = "unknown"


@dataclass
class DocumentElement:
    """Document element - unified data structure."""
    type: ElementType
    content: str
    level: int = 0  # For heading level or list level
    raw_data: Any = None  # Raw data for debugging or special processing
    table_data: List[List[str]] = field(default_factory=list)  # Table data
    image_path: Optional[str] = None  # Temporary image path
    has_merged_cells: bool = False  # Whether table has merged cells
    # Position-aware fields (for image semantic naming)
    para_index: int = 0  # Global paragraph index
    context_text: str = ""  # Context summary (for image naming)


# ============================================================================
# Abstract Base Parser
# ============================================================================

class BaseParser(ABC):
    """
    Document parser abstract base class.

    All format parsers must implement parse() method,
    returning unified DocumentElement list.
    """

    def __init__(self, temp_folder: str):
        """
        Initialize parser.

        Args:
            temp_folder: Temp folder path (for storing extracted images)
        """
        self.temp_folder = temp_folder
        self._temp_folder_created = False

    def _ensure_temp_folder(self) -> None:
        """Lazy create temp folder (only when first used)."""
        if not self._temp_folder_created:
            os.makedirs(self.temp_folder, exist_ok=True)
            self._temp_folder_created = True

    @abstractmethod
    def parse(self, file_path: str) -> List[DocumentElement]:
        """
        Parse document file.

        Args:
            file_path: Document file path

        Returns:
            List of DocumentElement
        """
        pass

    @abstractmethod
    def supports_extension(self, extension: str) -> bool:
        """
        Check if extension is supported.

        Args:
            extension: File extension (e.g., '.docx')

        Returns:
            True if supported
        """
        pass

    def _cleanup_temp_file(self, file_path: str) -> None:
        """Clean up temporary file."""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Cleanup temp file failed: {file_path}, {e}")

    def _convert_table_to_markdown(self, table_data: List[List[str]]) -> str:
        """Convert table data to Markdown format."""
        if not table_data:
            return ""

        col_widths = []
        num_cols = max(len(row) for row in table_data)

        for col_idx in range(num_cols):
            max_width = 0
            for row in table_data:
                if col_idx < len(row):
                    cell_len = len(row[col_idx])
                    max_width = max(max_width, cell_len)
            col_widths.append(max(max_width, 3))

        lines = []
        header = "|"
        separator = "|"
        for i, width in enumerate(col_widths):
            header += f" {table_data[0][i] if i < len(table_data[0]) else '':<{width}} |"
            separator += "-" * (width + 2) + "|"

        lines.append(header)
        lines.append(separator)

        for row_idx in range(1, len(table_data)):
            row = table_data[row_idx]
            row_str = "|"
            for i, width in enumerate(col_widths):
                cell_content = row[i] if i < len(row) else ""
                row_str += f" {cell_content:<{width}} |"
            lines.append(row_str)

        return "\n".join(lines)


# ============================================================================
# Parser Factory
# ============================================================================

class DocumentParserFactory:
    """
    Document parser factory.

    Automatically selects appropriate parser based on file extension.
    """

    # Extension to parser class mapping
    _parsers: Dict[str, type] = {}

    @classmethod
    def register(cls, extension: str) -> type:
        """
        Decorator: Register parser.

        Usage:
            @DocumentParserFactory.register('.docx')
            class DocxParser(BaseParser):
                ...
        """
        def decorator(parser_class: type) -> type:
            cls._parsers[extension.lower()] = parser_class
            return parser_class
        return decorator

    @classmethod
    def get_parser(cls, file_path: str, temp_folder: str = None) -> BaseParser:
        """
        Get appropriate parser instance.

        Args:
            file_path: File path
            temp_folder: Temp folder path

        Returns:
            Parser instance

        Raises:
            ValueError: Unsupported file format
        """
        if temp_folder is None:
            import tempfile
            temp_folder = os.path.join(tempfile.gettempdir(), "doc_parser_temp")

        ext = os.path.splitext(file_path)[1].lower()

        if ext not in cls._parsers:
            supported = ", ".join(cls._parsers.keys())
            raise ValueError(f"Unsupported file format: {ext}, supported: {supported}")

        parser_class = cls._parsers[ext]
        return parser_class(temp_folder)

    @classmethod
    def supported_extensions(cls) -> List[str]:
        """Get all supported extensions."""
        return list(cls._parsers.keys())

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if file is supported."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in cls._parsers


# ============================================================================
# .docx Parser
# ============================================================================

@DocumentParserFactory.register('.docx')
class DocxParser(BaseParser):
    """
    Word (.docx) document parser.

    Uses python-docx to parse modern Word documents.
    """

    # Heading level mapping (Word style name -> markdown level)
    HEADING_MAP = {
        "Heading 1": 1, "Heading 2": 2, "Heading 3": 3,
        "Heading 4": 4, "Heading 5": 5, "Heading 6": 6,
        "Heading 7": 7, "Heading 8": 8, "Heading 9": 9,
    }

    # Pre-compiled regex (for list item detection and cleanup)
    RE_NUMBERED_LIST = re.compile(r"^[\d]+\.?\s")
    RE_LETTER_LIST = re.compile(r"^[a-zA-Z]\.?\s")
    RE_LIST_PREFIX = re.compile(r"^[\d]+\.\s*|^[a-zA-Z]\.\s*|^[•·○●□■▪▫]\s*")
    RE_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')

    def __init__(self, temp_folder: str):
        super().__init__(temp_folder)
        self.image_counter = 0
        self.para_index = 0  # Paragraph index counter

    def supports_extension(self, extension: str) -> bool:
        return extension.lower() == '.docx'

    def parse(self, docx_path: str) -> List[DocumentElement]:
        """Parse Word document."""
        elements = []

        try:
            doc = Document(docx_path)
        except Exception as e:
            logger.error(f"Cannot open document {docx_path}: {e}")
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content=f"[Error: Cannot open document {os.path.basename(docx_path)} - {str(e)}]"
            )]

        # Reset counters
        self.para_index = 0
        self.image_counter = 0

        # Collect all paragraph and table elements
        body_elements = []
        for child in doc.element.body.iter():
            if isinstance(child, (CT_P, CT_Tbl)):
                body_elements.append(child)

        # Traverse elements, record paragraph index
        prev_text = ""
        for child in body_elements:
            try:
                if isinstance(child, CT_P):
                    para = Paragraph(child, doc)
                    para_text = clean_text(para.text)
                    self.para_index += 1

                    element = self._parse_paragraph(
                        child, doc,
                        para_index=self.para_index,
                        prev_text=prev_text
                    )
                    prev_text = para_text if para_text else prev_text
                else:
                    element = self._parse_table(child, doc)

                if element:
                    elements.append(element)
            except Exception as e:
                logger.warning(f"Parse element failed: {e}")
                element_type = type(child).__name__
                elements.append(DocumentElement(
                    type=ElementType.UNKNOWN,
                    content=f"[Parse failed: {element_type}]",
                    raw_data={
                        "error": str(e),
                        "element_type": element_type,
                        "para_index": self.para_index
                    },
                    para_index=self.para_index
                ))

        return elements

    def _parse_paragraph(self, element, doc: DocDocument,
                         para_index: int = 0, prev_text: str = "") -> Optional[DocumentElement]:
        """Parse paragraph element."""
        try:
            paragraph = Paragraph(element, doc)
            text = clean_text(paragraph.text)

            # Detect heading
            is_heading, level = self._is_heading(paragraph)
            if is_heading:
                return DocumentElement(
                    type=ElementType.HEADING,
                    content=text,
                    level=level,
                    raw_data=paragraph,
                    para_index=para_index,
                    context_text=text[:15] if text else prev_text[:15]
                )

            # Detect list
            is_list, list_type = self._is_list_item(paragraph)
            if is_list:
                content = self.RE_LIST_PREFIX.sub("", text)
                return DocumentElement(
                    type=ElementType.LIST_ITEM,
                    content=content,
                    level=1,
                    raw_data=paragraph,
                    para_index=para_index,
                    context_text=content[:15] if content else prev_text[:15]
                )

            # Detect image
            has_image, image_data = self._extract_images(paragraph, doc, para_index, prev_text)
            if has_image:
                image_path, context = image_data
                return DocumentElement(
                    type=ElementType.IMAGE,
                    content=text if text else context or "[Image]",
                    image_path=image_path,
                    raw_data=paragraph,
                    para_index=para_index,
                    context_text=context[:15] if context else prev_text[:15]
                )

            # Normal paragraph
            return DocumentElement(
                type=ElementType.PARAGRAPH,
                content=text,
                raw_data=paragraph,
                para_index=para_index,
                context_text=text[:15] if text else prev_text[:15]
            )
        except Exception as e:
            logger.warning(f"Parse paragraph failed: {e}")
            return None

    def _is_heading(self, paragraph: Paragraph) -> Tuple[bool, int]:
        """Determine if paragraph is heading."""
        try:
            style_name = paragraph.style.name if paragraph.style and paragraph.style.name else None
            if style_name in self.HEADING_MAP:
                return True, self.HEADING_MAP[style_name]

            # Check if starts with heading style
            text = clean_text(paragraph.text)
            if text and len(text) < 100:
                for run in paragraph.runs:
                    if run.bold and len(text) < 80:
                        return True, 1
            return False, 0
        except Exception as e:
            logger.warning(f"Check if bold heading failed: {e}")
            return False, 0

    def _is_list_item(self, paragraph: Paragraph) -> Tuple[bool, str]:
        """Determine if paragraph is list item."""
        try:
            text = paragraph.text.strip()
            if not text:
                return False, ""

            # Bullet points
            if text.startswith(("•", "·", "○", "●", "□", "■", "▪", "▫")):
                return True, "bullet"
            # Numbered list
            if self.RE_NUMBERED_LIST.match(text):
                return True, "number"
            if self.RE_LETTER_LIST.match(text):
                return True, "number"
            return False, ""
        except Exception as e:
            logger.warning(f"Check if list item failed: {e}")
            return False, ""

    def _extract_images(self, paragraph: Paragraph, doc: DocDocument,
                        para_index: int = 0, prev_text: str = "") -> Tuple[bool, Tuple[Optional[str], Optional[str]]]:
        """Extract embedded images from paragraph."""
        for run in paragraph.runs:
            blips = run._element.xpath(".//a:blip")
            if blips:
                try:
                    image_part = None
                    for elem in blips:
                        embed = elem.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                        if embed:
                            doc_part = doc.part
                            try:
                                image_part = doc_part.related_parts[embed]
                                break
                            except KeyError:
                                continue

                    if image_part:
                        self.image_counter += 1
                        para_text = clean_text(paragraph.text)
                        context = para_text[:15] if para_text else prev_text[:15]
                        context = self.RE_ILLEGAL_FILENAME_CHARS.sub('', context).strip()
                        if not context:
                            context = "img"

                        self._ensure_temp_folder()
                        image_filename = f"temp_{self.image_counter}.png"
                        image_path = os.path.join(self.temp_folder, image_filename)

                        with open(image_path, "wb") as f:
                            f.write(image_part.blob)

                        return True, (image_path, context)
                except Exception as e:
                    logger.warning(f"Extract image failed: {e}")
        return False, (None, None)

    def _parse_table(self, element, doc: DocDocument) -> Optional[DocumentElement]:
        """Parse table element - support merged cells, convert to HTML."""
        table = Table(element, doc)

        # Detect merged cells
        has_merged, cell_info = self._get_cell_info(table)

        # Extract table data
        table_data = []
        for row_idx, row in enumerate(table.rows):
            row_data = []
            for col_idx in range(len(table.rows[0].cells)):
                cell = row.cells[col_idx] if col_idx < len(row.cells) else None
                cell_text = clean_text(cell.text) if cell else ""
                row_data.append(cell_text)
            table_data.append(row_data)

        # Get cell attributes for HTML table
        cell_attrs = self._extract_cell_attributes(table, has_merged)

        # Generate table content
        if has_merged:
            html_table = self._convert_table_to_html(table_data, cell_attrs)
            return DocumentElement(
                type=ElementType.TABLE,
                content=html_table,
                table_data=table_data,
                raw_data={"table": table, "cell_attrs": cell_attrs, "has_merged": True},
                has_merged_cells=True
            )
        else:
            markdown_table = self._convert_table_to_markdown(table_data)
            return DocumentElement(
                type=ElementType.TABLE,
                content=markdown_table,
                table_data=table_data,
                raw_data={"table": table, "has_merged": False},
                has_merged_cells=False
            )

    def _get_cell_info(self, table: Table) -> Tuple[bool, Dict]:
        """Detect if table has merged cells."""
        try:
            cell_info = {
                "rowspan": {},
                "colspan": {},
            }

            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    tc = cell._tc
                    vMerge = tc.get_or_add_vMerge()
                    if vMerge and vMerge.val:
                        gridSpan = tc.get_or_add_gridSpan()
                        cell_info["rowspan"][(row_idx, col_idx)] = gridSpan.val if gridSpan else 1

                    gridSpan = tc.get_or_add_gridSpan()
                    if gridSpan and gridSpan.val > 1:
                        cell_info["colspan"][(row_idx, col_idx)] = gridSpan.val

            has_merged = bool(cell_info["rowspan"] or cell_info["colspan"])
            return has_merged, cell_info
        except Exception as e:
            logger.warning(f"Detect merged cells failed: {e}")
            return False, {}

    def _extract_cell_attributes(self, table: Table, has_merged: bool) -> List[List[Dict]]:
        """Extract each cell's attributes (rowspan, colspan)."""
        if not has_merged:
            rows = len(table.rows)
            cols = len(table.rows[0].cells) if table.rows else 0
            return [[{"rowspan": 1, "colspan": 1} for _ in range(cols)] for _ in range(rows)]

        attrs = []
        try:
            for row_idx, row in enumerate(table.rows):
                row_attrs = []
                for col_idx in range(len(table.rows[0].cells)):
                    cell = row.cells[col_idx] if col_idx < len(row.cells) else None
                    if cell:
                        tc = cell._tc
                        gridSpan = tc.get_or_add_gridSpan()
                        span = gridSpan.val if gridSpan else 1
                        vMerge = tc.get_or_add_vMerge()
                        is_continuation = vMerge and hasattr(vMerge, 'val') and vMerge.val == 2

                        row_attrs.append({
                            "rowspan": span if not is_continuation else 1,
                            "colspan": span,
                            "is_continuation": is_continuation
                        })
                    else:
                        row_attrs.append({"rowspan": 0, "colspan": 0, "skip": True})
                attrs.append(row_attrs)
        except Exception as e:
            logger.warning(f"Extract cell attributes failed: {e}")
            return []

        return attrs

    def _convert_table_to_html(self, table_data: List[List[str]],
                                cell_attrs: List[List[Dict]]) -> str:
        """Convert table data to HTML format (support merged cells)."""
        if not table_data:
            return ""

        rows = len(table_data)
        cols = len(table_data[0]) if table_data else 0

        processed = [[False for _ in range(cols)] for _ in range(rows)]

        html_lines = ['<table border="1" style="border-collapse: collapse; width: 100%;">']

        for row_idx in range(rows):
            html_lines.append('  <tr>')
            for col_idx in range(cols):
                if processed[row_idx][col_idx]:
                    continue

                cell_text = table_data[row_idx][col_idx] if row_idx < len(table_data) and col_idx < len(table_data[row_idx]) else ""

                rowspan = 1
                colspan = 1
                if cell_attrs and row_idx < len(cell_attrs) and col_idx < len(cell_attrs[row_idx]):
                    cell_attr = cell_attrs[row_idx][col_idx]
                    rowspan = cell_attr.get("rowspan", 1)
                    colspan = cell_attr.get("colspan", 1)

                for r in range(row_idx, min(row_idx + rowspan, rows)):
                    for c in range(col_idx, min(col_idx + colspan, cols)):
                        processed[r][c] = True

                style = 'style="padding: 8px; text-align: left;"'
                colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''

                html_lines.append(f'    <td{colspan_attr}{rowspan_attr} {style}>{cell_text}</td>')

            html_lines.append('  </tr>')

        html_lines.append('</table>')
        return '\n'.join(html_lines)


# ============================================================================
# .doc Parser (Windows Only)
# ============================================================================

@DocumentParserFactory.register('.doc')
class DocParser(BaseParser):
    """Legacy Word (.doc) parser using win32com."""

    def supports_extension(self, extension: str) -> bool:
        return extension.lower() == '.doc'

    def parse(self, doc_path: str) -> List[DocumentElement]:
        """Parse legacy Word document."""
        temp_docx = None
        try:
            temp_docx = self._convert_to_docx(doc_path)
            if not temp_docx:
                raise RuntimeError("Cannot convert .doc to .docx")

            docx_parser = DocxParser(self.temp_folder)
            return docx_parser.parse(temp_docx)

        except ImportError:
            logger.error("win32com not installed, cannot parse .doc files")
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content="[Error: .doc parsing requires pywin32, run: pip install pywin32]"
            )]
        except Exception as e:
            logger.error(f"Parse .doc failed: {e}")
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content=f"[Error: Cannot parse .doc file - {str(e)}]"
            )]
        finally:
            if temp_docx:
                self._cleanup_temp_file(temp_docx)

    def _convert_to_docx(self, doc_path: str) -> Optional[str]:
        """Convert .doc to .docx using win32com."""
        try:
            import win32com.client
        except ImportError:
            raise ImportError("pywin32 not installed")

        self._ensure_temp_folder()
        temp_docx = os.path.join(self.temp_folder, f"temp_{uuid.uuid4().hex[:8]}.docx")

        word = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False

            doc = word.Documents.Open(os.path.abspath(doc_path))
            doc.SaveAs2(os.path.abspath(temp_docx), FileFormat=16)
            doc.Close()
            doc = None

            return temp_docx

        except Exception as e:
            logger.warning(f"win32com conversion failed: {e}")
            self._cleanup_temp_file(temp_docx)
            return None
        finally:
            if word is not None:
                try:
                    word.Quit()
                except Exception as e:
                    logger.warning(f"Failed to quit win32com word instance: {e}")


# ============================================================================
# .pdf Parser
# ============================================================================

@DocumentParserFactory.register('.pdf')
class PdfParser(BaseParser):
    """PDF document parser using pdfplumber."""

    def supports_extension(self, extension: str) -> bool:
        return extension.lower() == '.pdf'

    def parse(self, pdf_path: str) -> List[DocumentElement]:
        """Parse PDF document."""
        try:
            import pdfplumber
        except ImportError:
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content="[Error: pdfplumber not installed, run: pip install pdfplumber]"
            )]

        elements = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract tables
                    tables = page.extract_tables()
                    if tables:
                        for table_idx, table in enumerate(tables):
                            table_element = self._create_table_element(table, page_num, table_idx)
                            elements.append(table_element)

                    # Extract text
                    text = page.extract_text()
                    if text:
                        lines = text.split('\n')
                        processed_elements = self._process_lines(lines)
                        elements.extend(processed_elements)

                    logger.info(f"Processed page {page_num}")

        except Exception as e:
            logger.error(f"Parse PDF failed: {e}")
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content=f"[Error: Cannot parse PDF - {str(e)}]"
            )]

        return elements

    def _process_lines(self, lines: List[str]) -> List[DocumentElement]:
        """Process text lines into elements."""
        processed_elements = []
        i = 0
        while i < len(lines):
            line = clean_text(lines[i])
            if not line:
                i += 1
                continue

            if self._is_likely_heading(line):
                processed_elements.append(DocumentElement(
                    type=ElementType.HEADING,
                    content=line,
                    level=2
                ))
                i += 1
            elif self._is_list_item(line):
                list_items = [line]
                j = i + 1
                while j < len(lines):
                    next_line = clean_text(lines[j])
                    if next_line and self._is_list_item(next_line):
                        list_items.append(next_line)
                        j += 1
                    else:
                        break

                merged_content = '\n'.join(list_items)
                processed_elements.append(DocumentElement(
                    type=ElementType.LIST_ITEM,
                    content=merged_content
                ))
                i = j
            else:
                processed_elements.append(DocumentElement(
                    type=ElementType.PARAGRAPH,
                    content=line
                ))
                i += 1

        return processed_elements

    def _is_likely_heading(self, text: str) -> bool:
        """Check if text is likely a heading."""
        if len(text) > 50:
            return False
        if '.' in text:
            return False
        heading_patterns = ['第', '章', '节', '附录', '目录', '摘要', '结论', '参考']
        for pattern in heading_patterns:
            if text.startswith(pattern):
                return True
        return False

    def _is_list_item(self, text: str) -> bool:
        """Check if text is a list item."""
        if not text:
            return False

        patterns = [
            r'^\d+[\.\)）]',
            r'^[a-zA-Z][\.\)）]',
            r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫⅲⅳⅴⅵⅶⅷⅸⅹ]+[\.\)）]?',
            r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑰⑱⑲⑳]+[\.\)）]?',
            r'^[一二三四五六七八九十百千]+、',
            r'^[•◦·○■□▸▹▪▫►▼▲△◆◇★☆✓✗✦✧]+\s',
            r'^[-–—]{1,3}\s+',
        ]

        for pattern in patterns:
            if re.match(pattern, text):
                return True
        return False

    def _create_table_element(self, table: List[List[str]],
                               page_num: int, table_idx: int) -> DocumentElement:
        """Create DocumentElement from table data."""
        cleaned_table = []
        for row in table:
            cleaned_row = [clean_text(cell) if cell else "" for cell in row]
            cleaned_table.append(cleaned_row)

        has_merged = self._detect_merged_cells(cleaned_table)

        if has_merged:
            html_table = self._convert_table_to_html(cleaned_table)
            return DocumentElement(
                type=ElementType.TABLE,
                content=html_table,
                table_data=cleaned_table,
                raw_data={"page": page_num, "table_idx": table_idx, "has_merged": True},
                has_merged_cells=True
            )
        else:
            markdown_table = self._convert_table_to_markdown(cleaned_table)
            return DocumentElement(
                type=ElementType.TABLE,
                content=markdown_table,
                table_data=cleaned_table,
                raw_data={"page": page_num, "table_idx": table_idx},
                has_merged_cells=False
            )

    def _detect_merged_cells(self, table_data: List[List[str]]) -> bool:
        """Detect if table has empty cells (possible merged)."""
        for row in table_data:
            for cell in row:
                if not cell or cell.strip() == "":
                    return True
        return False

    def _convert_table_to_html(self, table_data: List[List[str]]) -> str:
        """Convert table to HTML format."""
        if not table_data:
            return ""

        rows = len(table_data)
        cols = max(len(row) for row in table_data) if table_data else 0

        html_lines = ['<table border="1" style="border-collapse: collapse; width: 100%;">']

        for row_idx, row in enumerate(table_data):
            html_lines.append('  <tr>')
            for col_idx in range(cols):
                cell_text = row[col_idx] if col_idx < len(row) else ""
                cell_text = clean_text(cell_text)
                style = 'style="padding: 8px; text-align: left;"'
                html_lines.append(f'    <td {style}>{cell_text}</td>')
            html_lines.append('  </tr>')

        html_lines.append('</table>')
        return '\n'.join(html_lines)


# ============================================================================
# .xlsx / .xls Parser
# ============================================================================

@DocumentParserFactory.register('.xlsx')
@DocumentParserFactory.register('.xls')
class ExcelParser(BaseParser):
    """Excel parser using pandas/openpyxl."""

    def supports_extension(self, extension: str) -> bool:
        return extension.lower() in ('.xlsx', '.xls')

    def parse(self, excel_path: str) -> List[DocumentElement]:
        """Parse Excel document."""
        try:
            import pandas as pd
        except ImportError:
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content="[Error: pandas not installed, run: pip install pandas openpyxl]"
            )]

        elements = []
        temp_file = None

        try:
            # Convert .xls to .xlsx if needed
            if excel_path.endswith('.xls') and not excel_path.endswith('.xlsx'):
                temp_file = self._convert_xls_to_xlsx(excel_path)
                if temp_file:
                    excel_path = temp_file

            xl = pd.ExcelFile(excel_path)
            sheet_names = xl.sheet_names

            logger.info(f"Found {len(sheet_names)} worksheets: {sheet_names}")

            for sheet_name in sheet_names:
                elements.append(DocumentElement(
                    type=ElementType.HEADING,
                    content=f"Worksheet: {sheet_name}",
                    level=1
                ))

                df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
                table_data = self._clean_dataframe(df)

                if table_data:
                    has_merged = self._detect_merged_cells(table_data)

                    if has_merged:
                        html_table = self._convert_table_to_html(table_data)
                        elements.append(DocumentElement(
                            type=ElementType.TABLE,
                            content=html_table,
                            table_data=table_data,
                            raw_data={"sheet": sheet_name, "has_merged": True},
                            has_merged_cells=True
                        ))
                    else:
                        markdown_table = self._convert_table_to_markdown(table_data)
                        elements.append(DocumentElement(
                            type=ElementType.TABLE,
                            content=markdown_table,
                            table_data=table_data,
                            raw_data={"sheet": sheet_name},
                            has_merged_cells=False
                        ))

        except Exception as e:
            logger.error(f"Parse Excel failed: {e}")
            return [DocumentElement(
                type=ElementType.PARAGRAPH,
                content=f"[Error: Cannot parse Excel - {str(e)}]"
            )]
        finally:
            if temp_file:
                self._cleanup_temp_file(temp_file)

        return elements

    def _clean_dataframe(self, df) -> List[List[str]]:
        """Clean DataFrame data."""
        df = df.dropna(how='all')
        df = df.dropna(axis=1, how='all')

        if df.empty:
            return []

        table_data = []
        for _, row in df.iterrows():
            row_data = []
            for val in row:
                if pd.isna(val):
                    row_data.append("")
                elif isinstance(val, (int, float)):
                    row_data.append(str(val))
                else:
                    cell_text = str(val).strip().replace('\n', ' ')
                    row_data.append(cell_text)
            table_data.append(row_data)

        return table_data

    def _detect_merged_cells(self, table_data: List[List[str]]) -> bool:
        """Detect if table has empty cells."""
        for row in table_data:
            for cell in row:
                if not cell or cell.strip() == "":
                    return True
        return False

    def _convert_table_to_html(self, table_data: List[List[str]]) -> str:
        """Convert table to HTML format."""
        if not table_data:
            return ""

        rows = len(table_data)
        cols = max(len(row) for row in table_data) if table_data else 0

        html_lines = ['<table border="1" style="border-collapse: collapse; width: 100%;">']

        for row_idx, row in enumerate(table_data):
            html_lines.append('  <tr>')
            for col_idx in range(cols):
                cell_text = row[col_idx] if col_idx < len(row) else ""
                cell_text = clean_text(cell_text)
                style = 'style="padding: 8px; text-align: left;"'
                html_lines.append(f'    <td {style}>{cell_text}</td>')
            html_lines.append('  </tr>')

        html_lines.append('</table>')
        return '\n'.join(html_lines)

    def _convert_xls_to_xlsx(self, xls_path: str) -> Optional[str]:
        """Convert .xls to .xlsx."""
        try:
            from openpyxl import Workbook
            import xlrd

            self._ensure_temp_folder()
            temp_xlsx = os.path.join(self.temp_folder, f"temp_{uuid.uuid4().hex[:8]}.xlsx")

            workbook = xlrd.open_workbook(xls_path)
            wb = Workbook()
            wb.remove(wb.active)

            for sheet_name in workbook.sheet_names():
                sheet = workbook.sheet_by_name(sheet_name)
                ws = wb.create_sheet(title=sheet_name)

                for row_idx in range(sheet.nrows):
                    for col_idx in range(sheet.ncols):
                        cell_value = sheet.cell_value(row_idx, col_idx)
                        ws.cell(row=row_idx + 1, column=col_idx + 1, value=cell_value)

            wb.save(temp_xlsx)
            return temp_xlsx

        except Exception as e:
            logger.warning(f".xls conversion failed: {e}")
            return None


# ============================================================================
# Utility Functions
# ============================================================================

def create_parser(file_path: str, temp_folder: str = None) -> BaseParser:
    """
    Create appropriate parser for file.

    Args:
        file_path: File path
        temp_folder: Temp folder path

    Returns:
        Parser instance

    Raises:
        ValueError: Unsupported file format
    """
    return DocumentParserFactory.get_parser(file_path, temp_folder)


def parse_document(file_path: str, temp_folder: str = None) -> List[DocumentElement]:
    """
    Parse document file (convenience function).

    Args:
        file_path: File path
        temp_folder: Temp folder path

    Returns:
        List of DocumentElement
    """
    parser = create_parser(file_path, temp_folder)
    return parser.parse(file_path)


def get_supported_extensions() -> List[str]:
    """Get all supported extensions."""
    return DocumentParserFactory.supported_extensions()
