# -*- coding: utf-8 -*-
"""ChromaDB vector store manager for RAG pipeline.

Provides document storage and semantic search capabilities.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb

from aerospike_docs.core.schemas import ServiceResponse
from aerospike_docs.core.config import ApiConfig

logger = logging.getLogger(__name__)


class ChromaManager:
    """Manages ChromaDB vector database operations."""

    def __init__(self, collection_name: str = "docops_knowledge",
                 api_config: ApiConfig = None, project_root: Path = None):
        """Initialize ChromaDB client.

        Args:
            collection_name: Name of the collection to use
            api_config: API configuration instance. If None, uses default ApiConfig().
            project_root: Root directory for resolving relative paths
        """
        if api_config is None:
            api_config = ApiConfig()

        if project_root is None:
            project_root = Path.cwd()

        chroma_relative = api_config.chroma_db_dir

        # Handle both relative (./data/chroma_db) and absolute paths
        if Path(chroma_relative).is_absolute():
            self.db_dir = chroma_relative
        else:
            # Strip leading ./ if present
            chroma_path = chroma_relative.lstrip("./")
            self.db_dir = str((project_root / chroma_path).resolve())

        self.collection_name = collection_name

        # Ensure directory exists
        Path(self.db_dir).mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client with modern PersistentClient API
        self.client = chromadb.PersistentClient(
            path=str(self.db_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "DocOps knowledge base for RAG"}
        )

        logger.info(f"ChromaDB initialized at {self.db_dir}, collection: {collection_name}")

    def add_documents(
        self,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> ServiceResponse[bool]:
        """Add documents to the vector store.

        Args:
            documents: List of document texts
            embeddings: List of corresponding embeddings
            metadatas: List of metadata dicts
            ids: Optional list of IDs (auto-generated if not provided)

        Returns:
            ServiceResponse with success status
        """
        try:
            # Generate IDs if not provided
            if ids is None:
                ids = [f"doc_{i}" for i in range(len(documents))]

            # Validate input sizes
            if not (len(documents) == len(embeddings) == len(metadatas)):
                return ServiceResponse(
                    success=False,
                    data=False,
                    error_msg="Mismatch in documents, embeddings, and metadatas count"
                )

            # Add to collection
            self.collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )

            logger.info(f"Added {len(documents)} documents to collection")
            return ServiceResponse(success=True, data=True, error_msg="")

        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            return ServiceResponse(success=False, data=False, error_msg=str(e))

    def search(
        self,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> ServiceResponse[List[Dict[str, Any]]]:
        """Search for similar documents.

        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Optional metadata filter

        Returns:
            ServiceResponse with list of search results
        """
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where
            )

            # Format results
            formatted_results = []
            if results["documents"] and len(results["documents"]) > 0:
                for i in range(len(results["documents"][0])):
                    formatted_results.append({
                        "document": results["documents"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else 0.0,
                        "metadata": results["metadatas"][0][i] if "metadatas" in results else {},
                        "id": results["ids"][0][i] if "ids" in results else ""
                    })

            logger.info(f"Search returned {len(formatted_results)} results")
            return ServiceResponse(success=True, data=formatted_results, error_msg="")

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return ServiceResponse(success=False, data=[], error_msg=str(e))

    def get_collection_count(self) -> int:
        """Get the number of documents in the collection.

        Returns:
            Document count
        """
        return self.collection.count()

    def delete_collection(self) -> bool:
        """Delete the entire collection.

        Returns:
            True if successful
        """
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            return False
