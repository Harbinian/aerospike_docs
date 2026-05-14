# -*- coding: utf-8 -*-
"""RAG Question Answering Engine.

Combines vector search with LLM to generate answers with source citations.
"""

import json
import logging
import os
import re
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.schemas import ServiceResponse
from aerospike_docs.retrieval.embedder import MinimaxEmbedder
from aerospike_docs.retrieval.vector_store import ChromaManager

logger = logging.getLogger(__name__)


class RAGAnswerEngine:
    """RAG-powered question answering engine."""

    def __init__(self, api_config: ApiConfig = None, vector_store: ChromaManager = None):
        """Initialize RAG engine.

        Args:
            api_config: API configuration instance. If None, uses default ApiConfig().
            vector_store: Optional pre-configured ChromaManager instance.
        """
        if api_config is None:
            api_config = ApiConfig()

        self.api_config = api_config
        self.embedder = MinimaxEmbedder(api_config)
        self.vector_store = vector_store or ChromaManager(api_config=api_config)

    def _build_prompt(self, query: str, context_docs: List[Dict[str, Any]]) -> str:
        """Build prompt for LLM with context.

        Args:
            query: User query
            context_docs: Retrieved context documents

        Returns:
            Formatted prompt string
        """
        # Build context from retrieved documents
        context_parts = []
        for i, doc in enumerate(context_docs, 1):
            source = doc.get("metadata", {}).get("source_file", "Unknown")
            content = doc.get("document", "")[:500]  # Limit context length
            context_parts.append(f"[文档{i}] 来源: {source}\n{content}")

        context = "\n\n".join(context_parts)

        # Build prompt
        prompt = f"""你是一个严谨的业务架构师，也是一个专业的文档问答助手。请根据以下参考文档回答用户的问题。

要求：
1. 只根据提供的参考文档回答，不要编造信息
2. 如果无法从文档中找到答案，请明确说明"未找到相关信息"
3. 必须引用来源文档
4. 如果用户的提问涉及到"流程"、"步骤"、"流转"或"工作流"，你必须在回答的文本解释之后，使用 Mermaid 语法（如 graph TD 或 sequenceDiagram）绘制一张流程图。请将图表代码严格包裹在 ```mermaid 和 ``` 之间。图表节点尽量标明责任主体。

---
参考文档：
{context}

---
用户问题：{query}

回答："""

        return prompt

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM to generate answer.

        Args:
            prompt: Formatted prompt

        Returns:
            LLM response text or None on failure
        """
        url = self.api_config.minimax_api_url
        headers = {
            "Authorization": f"Bearer {self.api_config.minimax_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.api_config.minimax_model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=300)

            if response.status_code != 200:
                logger.error(f"LLM API returned {response.status_code}: {response.text[:500]}")
                return None

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"Unexpected LLM response format: {result}")
                return None

        except requests.Timeout:
            logger.error("LLM API timeout")
            return None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Log response details for debugging
            if 'response' in locals():
                logger.error(f"Response status: {response.status_code}")
                logger.error(f"Response body: {response.text[:500]}")
            return None

    def answer(
        self,
        query: str,
        top_k: int = 5
    ) -> ServiceResponse[Dict[str, Any]]:
        """Answer a question using RAG.

        Args:
            query: User question
            top_k: Number of documents to retrieve

        Returns:
            ServiceResponse with answer and sources
        """
        # Step 1: Embed query
        query_embedding = self.embedder.embed_query(query)
        if query_embedding is None:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg="Failed to embed query. Check API configuration."
            )

        # Step 2: Search vector store
        search_result = self.vector_store.search(query_embedding, n_results=top_k)
        if not search_result.success or not search_result.data:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg=f"Search failed: {search_result.error_msg}"
            )

        retrieved_docs = search_result.data
        logger.info(f"Retrieved {len(retrieved_docs)} documents for query: {query[:50]}...")

        # Step 3: Build prompt with context
        prompt = self._build_prompt(query, retrieved_docs)

        # Step 4: Call LLM
        answer = self._call_llm(prompt)
        if answer is None:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg="Failed to generate answer. Check LLM API configuration."
            )

        # Step 5: Extract source citations
        sources = []
        for doc in retrieved_docs:
            metadata = doc.get("metadata", {})
            sources.append({
                "file": metadata.get("source_file", "Unknown"),
                "full_path": metadata.get("full_path", ""),
                "section": metadata.get("section", "unknown"),
                "preview": doc.get("document", "")[:200]
            })

        result_data = {
            "answer": answer,
            "sources": sources,
            "query": query,
            "num_retrieved": len(retrieved_docs)
        }

        return ServiceResponse(success=True, data=result_data, error_msg="")


class GraphRAGEngine:
    """Graph-RAG engine using structured knowledge with entity co-occurrence.

    Uses entity-first retrieval: extracts entities from query, matches against
    structured_knowledge.json, and retrieves chunks containing matched entities.
    """

    STRUCTURED_KNOWLEDGE_PATH = Path("data/structured_knowledge.json")

    def __init__(self, api_config: ApiConfig = None,
                 knowledge_path: Path = None):
        """Initialize Graph-RAG engine.

        Args:
            api_config: API configuration instance. If None, uses default ApiConfig().
            knowledge_path: Path to structured_knowledge.json.
        """
        if api_config is None:
            api_config = ApiConfig()

        self.api_config = api_config
        if knowledge_path:
            self.STRUCTURED_KNOWLEDGE_PATH = knowledge_path
        self._knowledge_data = None

    def _load_knowledge_data(self) -> Optional[Dict[str, Any]]:
        """Load structured knowledge JSON with circuit breaker.

        Returns:
            Parsed JSON data or None on failure
        """
        if self._knowledge_data is not None:
            return self._knowledge_data

        try:
            if not self.STRUCTURED_KNOWLEDGE_PATH.exists():
                logger.error(f"Structured knowledge file not found: {self.STRUCTURED_KNOWLEDGE_PATH}")
                return None

            with open(self.STRUCTURED_KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
                self._knowledge_data = json.load(f)
                logger.info(f"Loaded structured knowledge: {len(self._knowledge_data.get('chunks', []))} chunks")
                return self._knowledge_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse structured knowledge JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load structured knowledge: {e}")
            return None

    def _extract_query_entities(self, query: str) -> List[str]:
        """Extract potential entities from user query using simple keyword matching.

        Args:
            query: User query string

        Returns:
            List of potential entity names found in query
        """
        # Load knowledge data to get all known entities
        knowledge = self._load_knowledge_data()
        if not knowledge:
            return []

        known_entities = set()
        for chunk in knowledge.get("chunks", []):
            for entity in chunk.get("entities", []):
                known_entities.add(entity.get("entity_name", "").lower())

        # Find which entities appear in the query
        query_lower = query.lower()
        matched_entities = []

        # Check for exact substring matches
        for entity in known_entities:
            if entity and entity in query_lower:
                matched_entities.append(entity)

        # Also add any word that looks like a potential entity (capitalized words)
        capitalized = re.findall(r'[A-Z][a-zA-Z]+', query)
        matched_entities.extend([w.lower() for w in capitalized])

        # Remove duplicates while preserving order
        seen = set()
        unique_entities = []
        for e in matched_entities:
            if e not in seen:
                seen.add(e)
                unique_entities.append(e)

        return unique_entities[:10]  # Limit to top 10 entities

    def _match_chunks_by_entities(self, query_entities: List[str]) -> List[Dict[str, Any]]:
        """Find chunks that contain the query entities.

        Args:
            query_entities: List of entity names to match

        Returns:
            List of matching chunks with entity evidence
        """
        knowledge = self._load_knowledge_data()
        if not knowledge:
            return []

        matched_chunks = []

        for chunk in knowledge.get("chunks", []):
            chunk_entities = chunk.get("entities", [])
            chunk_entity_names = {e.get("entity_name", "").lower() for e in chunk_entities}

            # Find which query entities match this chunk
            matched_entity_names = set(query_entities) & chunk_entity_names

            if matched_entity_names:
                # Collect evidence for matched entities
                entity_evidence = []
                for entity in chunk_entities:
                    if entity.get("entity_name", "").lower() in matched_entity_names:
                        entity_evidence.append({
                            "entity_name": entity.get("entity_name", ""),
                            "entity_type": entity.get("entity_type", ""),
                            "evidence_quote": entity.get("evidence_quote", "")
                        })

                matched_chunks.append({
                    "chunk_id": chunk.get("chunk_id", ""),
                    "source_file": chunk.get("source_file", ""),
                    "raw_text": chunk.get("raw_text", "")[:800],  # Limit text length
                    "matched_entities": entity_evidence,
                    "match_count": len(matched_entity_names)
                })

        # Sort by match count (most matches first)
        matched_chunks.sort(key=lambda x: x["match_count"], reverse=True)
        return matched_chunks[:15]  # Return top 15 chunks

    def _build_prompt(self, query: str, matched_chunks: List[Dict[str, Any]]) -> str:
        """Build prompt for LLM with entity-matched context.

        Args:
            query: User query
            matched_chunks: Matched chunks with entity evidence

        Returns:
            Formatted prompt string
        """
        # Build context from matched chunks
        context_parts = []
        for i, chunk in enumerate(matched_chunks, 1):
            source = chunk.get("source_file", "Unknown")
            text = chunk.get("raw_text", "")[:500]
            entities = chunk.get("matched_entities", [])

            entity_info = ", ".join([e["entity_name"] for e in entities]) if entities else "无"

            context_parts.append(
                f"[文档{i}] 来源: {source}\n"
                f"涉及实体: {entity_info}\n"
                f"内容: {text}"
            )

        context = "\n\n".join(context_parts)

        # Build prompt with Graph-RAG specific instructions
        prompt = f"""你是一个严谨的业务架构师，也是一个专业的文档问答助手。请根据以下参考文档（已通过实体匹配精准检索）回答用户的问题。

要求：
1. 只根据提供的参考文档回答，不要编造信息
2. 如果无法从文档中找到答案，请明确说明"未找到相关信息"
3. 必须引用来源文档和涉及的实体
4. 如果用户的提问涉及到"流程"、"步骤"、"流转"或"工作流"，你必须在回答的文本解释之后，使用 Mermaid 语法（如 graph TD 或 sequenceDiagram）绘制一张流程图。请将图表代码严格包裹在 ```mermaid 和 ``` 之间。图表节点尽量标明责任主体。

---
参考文档（基于实体匹配检索）：
{context}

---
用户问题：{query}

回答："""

        return prompt

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM to generate answer.

        Args:
            prompt: Formatted prompt

        Returns:
            LLM response text or None on failure
        """
        url = self.api_config.minimax_api_url
        headers = {
            "Authorization": f"Bearer {self.api_config.minimax_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.api_config.minimax_model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=300)

            if response.status_code != 200:
                logger.error(f"LLM API returned {response.status_code}: {response.text[:500]}")
                return None

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"Unexpected LLM response format: {result}")
                return None

        except requests.Timeout:
            logger.error("LLM API timeout")
            return None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    def answer(self, query: str) -> ServiceResponse[Dict[str, Any]]:
        """Answer a question using Graph-RAG (entity-first retrieval).

        Args:
            query: User question

        Returns:
            ServiceResponse with answer, sources, and entity evidence
        """
        # Step 1: Check if structured knowledge exists
        knowledge = self._load_knowledge_data()
        if not knowledge:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg="Structured knowledge not available. Please run structured_miner.py first."
            )

        # Step 2: Extract entities from query
        query_entities = self._extract_query_entities(query)
        logger.info(f"Query entities extracted: {query_entities}")

        if not query_entities:
            # Fallback: return a message asking for more specific query
            return ServiceResponse(
                success=False,
                data=None,
                error_msg="无法从问题中提取实体。请使用更具体的业务术语（如角色、部门、表单名称等）进行提问。"
            )

        # Step 3: Match chunks by entities
        matched_chunks = self._match_chunks_by_entities(query_entities)

        if not matched_chunks:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg=f"未找到包含实体 {query_entities} 的相关文档。请尝试其他关键词。"
            )

        logger.info(f"Matched {len(matched_chunks)} chunks for entities: {query_entities}")

        # Step 4: Build prompt with context
        prompt = self._build_prompt(query, matched_chunks)

        # Step 5: Call LLM
        answer = self._call_llm(prompt)
        if answer is None:
            return ServiceResponse(
                success=False,
                data=None,
                error_msg="Failed to generate answer. Check LLM API configuration."
            )

        # Step 6: Extract sources and entity evidence
        sources = []
        entity_evidence = []

        for chunk in matched_chunks:
            sources.append({
                "file": chunk.get("source_file", "Unknown"),
                "section": chunk.get("section", "unknown"),
                "chunk_id": chunk.get("chunk_id", ""),
                "preview": chunk.get("raw_text", "")[:200]
            })

            # Collect unique entity evidence
            for e in chunk.get("matched_entities", []):
                if e not in entity_evidence:
                    entity_evidence.append(e)

        result_data = {
            "answer": answer,
            "sources": sources,
            "entity_evidence": entity_evidence,
            "query": query,
            "query_entities": query_entities,
            "num_retrieved": len(matched_chunks)
        }

        return ServiceResponse(success=True, data=result_data, error_msg="")
