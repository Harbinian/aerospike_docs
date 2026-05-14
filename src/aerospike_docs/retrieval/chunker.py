# -*- coding: utf-8 -*-
"""Markdown chunker for RAG pipeline.

Splits markdown documents into chunks while preserving metadata.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class Chunk:
    """Represents a chunk of text with metadata."""

    def __init__(self, content: str, metadata: Dict[str, Any], chunk_index: int = 0):
        self.content = content
        self.metadata = metadata
        self.chunk_index = chunk_index

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for vector store."""
        return {
            "content": self.content,
            "metadata": self.metadata
        }


class MarkdownChunker:
    """Splits markdown documents into semantic chunks."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Initialize chunker.

        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between chunks to preserve context
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_file(self, file_path: Path) -> List[Chunk]:
        """Chunk a single markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            List of Chunk objects
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return []

        # Extract metadata from filename
        filename = file_path.stem
        metadata = {
            "source_file": filename,
            "full_path": str(file_path)
        }

        # Split by headers to preserve semantic structure
        chunks = self._split_by_headers(content, metadata)

        return chunks

    def _split_by_headers(self, content: str, base_metadata: Dict[str, Any]) -> List[Chunk]:
        """Split content by markdown headers."""
        lines = content.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = 0

        for line in lines:
            line_size = len(line)

            # If single line exceeds chunk size, force split
            if line_size > self.chunk_size:
                # Flush current chunk
                if current_chunk:
                    chunk_text = '\n'.join(current_chunk)
                    metadata = {**base_metadata, "section": "mixed"}
                    chunks.append(Chunk(chunk_text, metadata, chunk_index))
                    chunk_index += 1
                    current_chunk = []
                    current_size = 0

                # Split long line into smaller pieces
                for i in range(0, line_size, self.chunk_size - 100):
                    piece = line[i:i + self.chunk_size - 100]
                    metadata = {**base_metadata, "section": "long_line"}
                    chunks.append(Chunk(piece, metadata, chunk_index))
                    chunk_index += 1
                continue

            # Check if adding this line would exceed limit
            if current_size + line_size > self.chunk_size and current_chunk:
                chunk_text = '\n'.join(current_chunk)
                # Determine section type
                section = "content"
                for l in current_chunk:
                    if l.startswith('# '):
                        section = "title"
                    elif l.startswith('## '):
                        section = "section"
                    elif l.startswith('### '):
                        section = "subsection"

                metadata = {**base_metadata, "section": section}
                chunks.append(Chunk(chunk_text, metadata, chunk_index))
                chunk_index += 1

                # Start new chunk with overlap
                overlap_lines = current_chunk[-2:] if len(current_chunk) >= 2 else current_chunk
                current_chunk = overlap_lines
                current_size = sum(len(l) for l in overlap_lines)

            current_chunk.append(line)
            current_size += line_size

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = '\n'.join(current_chunk)
            metadata = {**base_metadata, "section": "content"}
            chunks.append(Chunk(chunk_text, metadata, chunk_index))

        return chunks

    def chunk_directory(self, directory: Path, pattern: str = "*.md") -> List[Chunk]:
        """Chunk all markdown files in a directory.

        Args:
            directory: Directory containing markdown files
            pattern: File pattern to match

        Returns:
            List of all chunks from all files
        """
        all_chunks = []

        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            return all_chunks

        # Use rglob for recursive search to find all .md files in subdirectories
        md_files = list(directory.rglob(pattern))

        # Exclude english_backup and attachments
        md_files = [f for f in md_files
                    if 'english_backup' not in str(f) and 'attachments' not in str(f)]

        logger.info(f"Found {len(md_files)} markdown files to chunk")

        for md_file in md_files:
            chunks = self.chunk_file(md_file)
            all_chunks.extend(chunks)
            logger.debug(f"Chunked {md_file.name} into {len(chunks)} chunks")

        logger.info(f"Total chunks created: {len(all_chunks)}")
        return all_chunks
