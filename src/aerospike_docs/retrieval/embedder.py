# -*- coding: utf-8 -*-
"""Minimax Embedding service for RAG pipeline.

Handles text vectorization using Minimax Embedding API.
"""

import logging
import requests
from typing import List, Optional, Dict, Any
from aerospike_docs.core.config import ApiConfig

logger = logging.getLogger(__name__)


class MinimaxEmbedder:
    """Wrapper for Minimax Embedding API."""

    def __init__(self, api_config: ApiConfig = None):
        """Initialize embedder with config.

        Args:
            api_config: API configuration instance. If None, uses default ApiConfig().
        """
        if api_config is None:
            api_config = ApiConfig()

        self.api_key = api_config.minimax_api_key
        self.api_url = api_config.minimax_api_url
        self.embedding_model = api_config.minimax_embedding_model

        if not self.api_key:
            logger.warning("MINIMAX_API_KEY not configured - embedding disabled")

    def embed_texts(self, texts: List[str], embed_type: str = "db") -> Optional[List[List[float]]]:
        """Generate embeddings for texts.

        Args:
            texts: List of text strings to embed
            embed_type: "db" for database indexing, "query" for search queries

        Returns:
            List of embedding vectors, or None on failure
        """
        if not self.api_key:
            logger.error("API key not configured")
            return None

        # CRITICAL: Must include "type" parameter!
        # "db" for building vector database
        # "query" for search queries
        # Without this, API returns 2013 invalid params error
        payload = {
            "model": self.embedding_model,
            "texts": texts,
            "type": embed_type  # This is the critical parameter!
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            # Use correct Minimax Embedding API endpoint
            embedding_url = "https://api.minimax.chat/v1/embeddings"
            response = requests.post(
                embedding_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code != 200:
                logger.error(f"Embedding API error: {response.status_code} - {response.text}")
                return None

            result = response.json()

            # Extract embeddings from response
            # Minimax API returns: {"base_resp": {...}, "vectors": [[...], [...]]}
            embeddings = result.get("vectors", [])

            if not embeddings:
                logger.warning(f"Empty embeddings in response: {result}")
                return None

            logger.info(f"Successfully generated {len(embeddings)} embeddings")
            return embeddings

        except requests.Timeout:
            logger.error("Embedding API timeout")
            return None
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    def embed_query(self, query: str) -> Optional[List[float]]:
        """Generate embedding for a search query.

        Args:
            query: Query text

        Returns:
            Query embedding vector, or None on failure
        """
        embeddings = self.embed_texts([query], embed_type="query")
        return embeddings[0] if embeddings else None

    def embed_documents(self, documents: List[str]) -> Optional[List[List[float]]]:
        """Generate embeddings for document chunks (database building).

        Args:
            documents: List of document texts

        Returns:
            List of document embeddings, or None on failure
        """
        return self.embed_texts(documents, embed_type="db")
