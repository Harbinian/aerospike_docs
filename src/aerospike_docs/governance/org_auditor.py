# -*- coding: utf-8 -*-
"""Organization auditor service for role compliance and organizational structure."""

import json
import re
import glob
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any


class OrganizationAuditor:
    """Service for auditing organization roles and compliance.

    Handles:
    - Role mapping management (load/save)
    - Official organization chart management
    - Role evidence extraction from documents
    - Set-theory based org comparison (official vs actual)
    - Role synchronization from glossary to role mapping
    """

    def __init__(self, project_root: Path = None):
        """Initialize the organization auditor.

        Args:
            project_root: Root directory of the project. Defaults to current directory.
        """
        self.project_root = project_root or Path.cwd()
        self.config_dir = self.project_root / "config"
        self.outputs_dir = self.project_root / "outputs"
        self.glossary_path = self.project_root / "glossary.yaml"
        self.flowchart_path = self.project_root / "dist" / "flowchart_extractions.json"

    # ============================================================
    # Role Mapping Operations
    # ============================================================

    def load_role_mapping(self) -> Dict[str, Any]:
        """Load role mapping from config file with auto-migration."""
        config_path = self.config_dir / "role_mapping.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Auto-migrate from old format (2-level) to new format (4-level)
                mappings = data.get("mappings", [])
                if mappings:
                    first = mappings[0]
                    # Check if it's old format (has 'department' but no 'role')
                    if "department" in first and "role" not in first:
                        # Migrate
                        new_mappings = []
                        for m in mappings:
                            old_dept = m.get("department", "")
                            old_roles = m.get("roles", [])
                            if isinstance(old_roles, str):
                                old_roles = [old_roles]
                            elif not isinstance(old_roles, list):
                                old_roles = []

                            for role in old_roles:
                                new_mappings.append({
                                    "company": "⚠️ 待分配" if "示例" in old_dept else old_dept,
                                    "department": old_dept if "示例" not in old_dept else "⚠️ 待分配",
                                    "office": "⚠️ 待分配",
                                    "role": role
                                })

                        data["mappings"] = new_mappings
                        data["metadata"]["version"] = "2.0"

                        # Save migrated data
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)

                return data
            except Exception as e:
                print(f"加载配置失败: {e}")
                return {"mappings": [], "metadata": {}}
        return {"mappings": [], "metadata": {}}

    def save_role_mapping(self, data: Dict[str, Any]) -> bool:
        """Save role mapping to config file."""
        config_path = self.config_dir / "role_mapping.json"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def load_official_org_data(self) -> Dict[str, List]:
        """Load 2D hierarchical org structure from data/official_org.json."""
        data_path = self.project_root / "data" / "official_org.json"
        if data_path.exists():
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载主数据失败: {e}")
        return {"mappings": [], "metadata": {"version": "3.1", "updated_at": ""}}

    def load_aliases_dict(self) -> Dict[str, str]:
        """Load aliases.json as flat key-value mapping.

        Returns:
            Dict where keys are aliases, values are standard terms
            Example: {"科创部": "科技创新部", "工装办": "工艺装备室"}
        """
        aliases_path = self.project_root / "data" / "aliases.json"
        if aliases_path.exists():
            try:
                with open(aliases_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载别名映射失败: {e}")
        return {}

    def translate_to_standard(self, entity: str, aliases: Dict[str, str]) -> str:
        """Translate entity to standard term using aliases.json (flat key-value).

        Args:
            entity: The entity to translate
            aliases: Flat key-value mapping from aliases.json

        Returns:
            Standard term if entity is a key in aliases, otherwise original entity
        """
        return aliases.get(entity, entity)

    def is_valid_entity(self, entity: str, org_data: Dict, aliases: Dict[str, str]) -> bool:
        """Check if entity is valid using 2D hierarchical + vacuum filter + English filter.

        Logic:
        1. Translate entity via aliases.json
        2. Flatten all values from mappings to a set (with vacuum filter)
        3. Filter out English-only entities from valid set
        4. Check if translated entity exists in the set

        Args:
            entity: Entity to validate
            org_data: 2D hierarchical org data with mappings array
            aliases: Flat aliases mapping

        Returns:
            True if valid, False if wild
        """
        if not entity or "示例" in entity:
            return False

        # Step 1: Translate
        translated = self.translate_to_standard(entity, aliases)

        # Step 2: Dynamic net + Vacuum filter + English filter
        valid_entities_set = set()
        for mapping in org_data.get("mappings", []):
            for val in mapping.values():
                # 🚨 Vacuum filter: skip empty/None/whitespace
                if val and str(val).strip():
                    val_str = str(val).strip()
                    # 🚨 English filter: skip pure English entities
                    if not self.is_english_only(val_str):
                        valid_entities_set.add(val_str)

        # Step 3: Validate
        return translated.strip() in valid_entities_set

    # ============================================================
    # Official Organization Chart Operations
    # ============================================================

    def load_official_org_chart(self) -> Dict[str, Any]:
        """Load official organization chart from config file."""
        config_path = self.config_dir / "official_org_chart.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载官方架构失败: {e}")
                return {"mappings": [], "metadata": {}}
        return {"mappings": [], "metadata": {}}

    def save_official_org_chart(self, data: Dict[str, Any]) -> bool:
        """Save official organization chart to config file."""
        config_path = self.config_dir / "official_org_chart.json"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存官方架构失败: {e}")
            return False

    # ============================================================
    # Utility Functions
    # ============================================================

    def is_english_only(self, text: str) -> bool:
        """Check if text contains only English letters, spaces, and basic punctuation.

        Args:
            text: Text to check

        Returns:
            True if text is English-only (no Chinese characters)
        """
        if not text:
            return False
        # Match only ASCII letters, spaces, hyphens, underscores, parentheses
        return bool(re.match(r'^[A-Za-z0-9\s\-_()]+$', text.strip()))

    # ============================================================
    # Evidence Extraction
    # ============================================================

    def _extract_context(self, line: str, keyword: str, context_chars: int = 40) -> str:
        """Extract context around keyword with highlighting.

        Args:
            line: Full line containing the keyword
            keyword: Keyword to highlight
            context_chars: Number of characters to show before/after keyword

        Returns:
            Context string with keyword highlighted in **bold**
        """
        idx = line.find(keyword)
        if idx == -1:
            return line[:200]

        start = max(0, idx - context_chars)
        end = min(len(line), idx + len(keyword) + context_chars)

        context = line[start:end]

        # Highlight entity with **bold**
        highlighted = context.replace(keyword, f"**{keyword}**")

        # Add ellipsis indicators
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(line) else ""

        return f"{prefix}{highlighted}{suffix}"

    def grep_role_evidence_from_markdown(self, roles: Set[str]) -> Dict[str, List[Dict[str, str]]]:
        """Search for role evidence in Markdown files with context extraction.

        Args:
            roles: Set of role names to search for

        Returns:
            Dict mapping role name to list of {doc, evidence} dicts
        """
        role_sources = {}

        if not self.outputs_dir.exists():
            return role_sources

        # Find all .md files, excluding english_backup and attachments
        md_files = []
        for pattern in ["**/*.md", "**/*.MD"]:
            md_files.extend(self.outputs_dir.glob(pattern))

        # Filter out english_backup and attachments
        md_files = [f for f in md_files if "english_backup" not in str(f) and "attachments" not in str(f)]

        print(f"[Grep Engine] Searching {len(md_files)} Markdown files for {len(roles)} roles...")

        for role in roles:
            found_evidence = []
            for md_file in md_files:
                if len(found_evidence) >= 2:  # Max 2 sources per role
                    break

                try:
                    with open(md_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if role in line and len(line.strip()) > 10:
                                stripped = line.strip()
                                if len(stripped) > 10 and not stripped.startswith("#"):
                                    # Extract context with highlighting
                                    context = self._extract_context(stripped, role, context_chars=40)
                                    found_evidence.append({
                                        "doc": md_file.stem,
                                        "evidence": context
                                    })
                                    break
                except Exception:
                    continue

            if found_evidence:
                role_sources[role] = found_evidence

        print(f"[Grep Engine] Found evidence for {len(role_sources)} roles")
        return role_sources

    def load_role_sources_from_flowchart(self) -> Dict[str, List[Dict[str, str]]]:
        """Load role sources from flowchart_extractions.json.

        Returns:
            Dict mapping role name to list of {doc, evidence} dicts
        """
        role_sources = {}

        if self.flowchart_path.exists():
            try:
                with open(self.flowchart_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for extraction in data.get("extractions", []):
                    doc_name = extraction.get("document", "")
                    for process in extraction.get("processes", []):
                        process_name = process.get("process_name", "")
                        for actor in process.get("actors", []):
                            if actor:
                                # Filter out English-only roles
                                if self.is_english_only(actor):
                                    continue
                                if actor not in role_sources:
                                    role_sources[actor] = []
                                existing_docs = [d["doc"] for d in role_sources[actor]]
                                if doc_name not in existing_docs:
                                    role_sources[actor].append({
                                        "doc": doc_name,
                                        "evidence": f"流程: {process_name}"
                                    })
            except Exception as e:
                print(f"读取流程图数据失败: {e}")

        return role_sources

    # ============================================================
    # Glossary Integration
    # ============================================================

    def get_actual_roles_from_glossary(self) -> Tuple[Set[str], Dict[str, List[Dict[str, str]]]]:
        """Extract actual roles from glossary.yaml.

        Returns:
            (roles_set, role_sources_dict) - Tuple of roles set and role->sources mapping
        """
        import yaml
        actual_roles: Set[str] = set()
        role_sources: Dict[str, List[Dict[str, str]]] = {}

        role_categories = ["岗位角色", "人员角色", "工装管理角色", "组织角色", "组织职责"]

        if self.glossary_path.exists():
            try:
                with open(self.glossary_path, 'r', encoding='utf-8') as f:
                    glossary = yaml.safe_load(f)

                for entity in glossary.get("entities", []):
                    category = entity.get("category", "")
                    if category in role_categories:
                        name = entity.get("name", "").strip()

                        # Filter out English-only roles (dirty data)
                        if name and "示例" not in name:
                            if not self.is_english_only(name):
                                actual_roles.add(name)

                        # Also check aliases
                        for alias in entity.get("aliases", []):
                            alias = alias.strip()
                            if alias and "示例" not in alias:
                                if not self.is_english_only(alias):
                                    actual_roles.add(alias)
            except Exception as e:
                print(f"读取术语表失败: {e}")

        # Merge with flowchart data for richer source info
        flowchart_sources = self.load_role_sources_from_flowchart()
        for role, sources in flowchart_sources.items():
            if role not in role_sources:
                role_sources[role] = []
            for source in sources:
                if not any(d.get("doc") == source.get("doc") for d in role_sources[role]):
                    role_sources[role].append(source)

        return actual_roles, role_sources

    # ============================================================
    # Organization Comparison
    # ============================================================

    def _get_all_glossary_entities_with_sources(self) -> Tuple[Set[str], Dict[str, List[str]]]:
        """Get entities from glossary.yaml with sources (relevant to org structure only).

        Returns:
            Tuple of (entities_set, entity_to_sources_dict)

        Only includes categories related to:
        - 组织 / 组织架构 / 组织机构 (Organization)
        - 岗位角色 / 人员角色 / 工装管理角色 (Roles)
        - 工装管理部门 (Tooling Management Department)

        Filters out:
        - Pure English entities (e.g., "technician", "Planner")
        - Example/placeholder text ("示例")
        """
        all_entities = set()
        entity_sources: Dict[str, List[str]] = {}

        # Categories relevant to org structure validation
        valid_categories = {
            "组织", "组织架构", "组织机构",
            "岗位角色", "人员角色", "工装管理角色",
            "工装管理部门"
        }

        import yaml
        import re

        if self.glossary_path.exists():
            with open(self.glossary_path, 'r', encoding='utf-8') as f:
                glossary = yaml.safe_load(f)
            for entity in glossary.get("entities", []):
                category = entity.get("category", "")

                # Filter by category - only include org/role related
                if category not in valid_categories:
                    continue

                name = entity.get("name", "").strip()
                source = entity.get("source", "").strip()

                # Filter: Skip pure English entities
                if name and "示例" not in name:
                    if re.match(r'^[A-Za-z\s]+$', name):
                        continue  # Skip pure English
                    all_entities.add(name)
                    # Add source
                    if name not in entity_sources:
                        entity_sources[name] = []
                    if source and source not in entity_sources[name]:
                        entity_sources[name].append(source)

                # Also check aliases
                for alias in entity.get("aliases", []):
                    alias = alias.strip()
                    if alias and "示例" not in alias:
                        # Filter: Skip pure English aliases
                        if re.match(r'^[A-Za-z\s]+$', alias):
                            continue
                        all_entities.add(alias)
                        # Add source for alias
                        if alias not in entity_sources:
                            entity_sources[alias] = []
                        if source and source not in entity_sources[alias]:
                            entity_sources[alias].append(source)

        return all_entities, entity_sources

    def get_entity_sources_hybrid(self, entity: str, source_from_glossary: str) -> List[Dict[str, str]]:
        """混合溯源：先查 glossary source，无效则 Grep 回退。

        Args:
            entity: Entity name to find sources for
            source_from_glossary: Source value from glossary.yaml

        Returns:
            List of {doc, evidence} dicts
        """
        results: List[Dict[str, str]] = []

        # 步骤 1: 检查 glossary 中的 source 是否有效
        if source_from_glossary and source_from_glossary.strip():
            # 有效 source 判断：非空且不包含垃圾文本
            if "Mined from outputs documents" not in source_from_glossary:
                results.append({
                    "doc": source_from_glossary,
                    "evidence": f"来源: {source_from_glossary}"
                })

        # 步骤 2: 如果没有有效 source，触发 Grep 回退
        if not results:
            grep_results = self.grep_role_evidence_from_markdown({entity})
            if entity in grep_results:
                for src in grep_results[entity]:
                    results.append({
                        "doc": src.get("doc", "Unknown"),
                        "evidence": src.get("evidence", "")
                    })

        return results

    def perform_org_comparison(self) -> Dict[str, Any]:
        """Perform 2D hierarchical validation with vacuum filter + hybrid sourcing.

        Uses the new Schema-Guided approach:
        1. Load official org data (mappings array with 2D hierarchy)
        2. Load aliases.json for flat key-value translation
        3. For each glossary entity, check if valid via dynamic net + vacuum filter
        4. Wild entities = not found in any dimension
        5. Sources: Hybrid - use glossary source if valid, else Grep fallback

        Returns:
            dict with keys: valid_entities, wild_entities, org_data, dimension_breakdown
        """
        # Load 2D hierarchical org data
        org_data = self.load_official_org_data()

        # Load aliases for translation (flat key-value)
        aliases = self.load_aliases_dict()

        # Get all entities from glossary WITH sources (filters English, gets sources)
        all_glossary_entities, entity_sources = self._get_all_glossary_entities_with_sources()

        # Validate each entity against 2D hierarchy + vacuum filter + aliases
        valid_entities = set()
        wild_entities = set()

        for entity in all_glossary_entities:
            if self.is_valid_entity(entity, org_data, aliases):
                valid_entities.add(entity)
            else:
                wild_entities.add(entity)

        # Get dimension breakdown (mappings count)
        dimension_breakdown = {
            "mappings_count": len(org_data.get("mappings", []))
        }

        # Hybrid sourcing: use glossary source if valid, else Grep fallback
        wild_role_sources: Dict[str, List[Dict[str, str]]] = {}
        for entity in wild_entities:
            source_from_glossary = entity_sources.get(entity, [""])[0] if entity_sources.get(entity) else ""
            # 调用混合溯源函数
            sources = self.get_entity_sources_hybrid(entity, source_from_glossary)
            wild_role_sources[entity] = sources

        return {
            "valid_entities": list(valid_entities),
            "wild_entities": list(wild_entities),
            "wild_role_sources": wild_role_sources,
            "org_data": org_data,
            "dimension_breakdown": dimension_breakdown,
            "total_glossary_entities": len(all_glossary_entities),
            "validation_method": "2D hierarchical + vacuum filter + alias translation + hybrid sourcing"
        }

    # ============================================================
    # Role Synchronization
    # ============================================================

    def sync_roles_from_data(self) -> Tuple[bool, str, int]:
        """Sync roles from business data to role_mapping.json.

        Returns:
            (success: bool, message: str, added_count: int)
        """
        import yaml
        role_data = self.load_role_mapping()
        existing_roles: Set[str] = set()

        # Migrate old format (2-level) to new format (4-level)
        migrated = False
        for m in role_data.get("mappings", []):
            if "department" in m and "roles" in m:
                old_dept = m.get("department", "")
                old_roles = m.get("roles", "")
                if isinstance(old_roles, str):
                    old_roles = [old_roles]
                elif not isinstance(old_roles, list):
                    old_roles = []

                new_mappings = []
                for role in old_roles:
                    new_mappings.append({
                        "company": "⚠️ 待分配" if "示例" in old_dept else old_dept,
                        "department": old_dept if "示例" not in old_dept else "⚠️ 待分配",
                        "office": "⚠️ 待分配",
                        "role": role
                    })

                idx = role_data["mappings"].index(m)
                role_data["mappings"][idx:idx+1] = new_mappings
                migrated = True

        if migrated:
            role_data["metadata"]["version"] = "2.0"
            role_data["metadata"]["updated_at"] = __import__('datetime').datetime.now().strftime("%Y-%m-%d")
            self.save_role_mapping(role_data)

        # Collect existing roles
        for m in role_data.get("mappings", []):
            role = m.get("role", "")
            if role:
                existing_roles.add(role.strip())

        new_roles: List[str] = []

        # Extract roles from glossary.yaml
        role_categories = ["岗位角色", "人员角色", "工装管理角色", "组织角色", "组织职责"]

        if self.glossary_path.exists():
            try:
                with open(self.glossary_path, 'r', encoding='utf-8') as f:
                    glossary = yaml.safe_load(f)

                for entity in glossary.get("entities", []):
                    category = entity.get("category", "")
                    if category in role_categories:
                        name = entity.get("name", "").strip()
                        if name and name not in existing_roles and "示例" not in name:
                            new_roles.append(name)

                for entity in glossary.get("entities", []):
                    category = entity.get("category", "")
                    if category in role_categories:
                        for alias in entity.get("aliases", []):
                            alias = alias.strip()
                            if alias and alias not in existing_roles and "示例" not in alias:
                                new_roles.append(alias)
            except Exception as e:
                return False, f"读取术语表失败: {e}", 0

        # Deduplicate
        new_roles = list(set(new_roles))

        if not new_roles:
            return True, "未发现新角色", 0

        # Add new roles to mapping with 4-level structure
        for role in new_roles:
            role_data["mappings"].append({
                "company": "⚠️ 待分配",
                "department": "⚠️ 待分配",
                "office": "⚠️ 待分配",
                "role": role
            })

        # Update metadata
        role_data["metadata"]["version"] = "2.0"
        role_data["metadata"]["updated_at"] = __import__('datetime').datetime.now().strftime("%Y-%m-%d")

        # Save
        if self.save_role_mapping(role_data):
            return True, f"成功添加 {len(new_roles)} 个新角色", len(new_roles)
        else:
            return False, "保存失败", 0
