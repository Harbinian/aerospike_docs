# -*- coding: utf-8 -*-
"""Knowledge Graph Builder Domain Service.

Encapsulates logic from:
- scripts/map_knowledge.py (graph mapping)
- scripts/visualize_graph.py (visualization)
"""

import json
import re
import yaml
from aerospike_docs.core.document_codes import code_patterns, load_doc_prefixes
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional, Set, Tuple



# =============================================================================
# CONSTANTS - Level and Group Definitions
# =============================================================================
LEVEL_PATTERNS = {
    0: ['手册', '总纲', '总则', '纲领'],
    1: ['规范', '办法', '程序', '制度', '标准', '准则', '规程'],
    2: ['细则', '指导书', '指南', '说明', '指引', '工艺', '技术'],
    3: ['表单', '记录', '卡', '单', '清单', '台账', '登记表']
}

DOC_CODE_PATTERNS = code_patterns()


class GraphBuilder:
    """Domain Service for knowledge graph building and visualization.

    Extracts core logic from map_knowledge.py and visualize_graph.py.
    """

    def __init__(self, project_root: Path = None):
        """Initialize GraphBuilder.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root or Path.cwd()
        self.doc_prefixes = load_doc_prefixes(self.project_root)

        # STRICT: Only read from refined_outputs (Fail Fast if not exists)
        self.outputs_dir = self.project_root / "refined_outputs"
        if not self.outputs_dir.exists():
            raise FileNotFoundError(
                f"[FATAL] refined_outputs directory not found at: {self.outputs_dir}\n"
                f"Pipeline broken: Knowledge graph requires refined_outputs as single source of truth.\n"
                f"Please run term governance first: python scripts/govern_terms.py"
            )

        self.dist_dir = self.project_root / "dist"
        self._aliases_cache = None

    # ==========================================================================
    # Aliases Interceptor (D5-2)
    # ==========================================================================
    def load_aliases(self) -> Dict[str, List[str]]:
        """Load aliases.json with caching."""
        if self._aliases_cache is None:
            aliases_path = self.project_root / "data" / "aliases.json"
            if aliases_path.exists():
                with open(aliases_path, 'r', encoding='utf-8') as f:
                    self._aliases_cache = json.load(f)
            else:
                self._aliases_cache = {}
        return self._aliases_cache

    def normalize_term(self, term: str) -> str:
        """Normalize term using aliases mapping."""
        if not term:
            return term
        aliases = self.load_aliases()
        # Check if term is a wild term, map to standard term
        for std_term, wild_terms in aliases.items():
            if term in wild_terms:
                return std_term
        return term

    def apply_aliases_to_entities(self, entities: List[str]) -> List[str]:
        """Apply aliases normalization to entity list."""
        return [self.normalize_term(e) for e in entities]

    # ==========================================================================
    # Graph Mapping Methods (from map_knowledge.py)
    # ==========================================================================
    def load_glossary(self) -> dict:
        """Load glossary.yaml."""
        glossary_path = self.project_root / "glossary.yaml"
        with open(glossary_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def normalize_doc_code(self, code: str) -> str:
        """Normalize document code by removing spaces."""
        return code.replace(' ', '').replace(' ', '').strip()

    def build_whitelists(self, glossary: dict) -> Tuple[Set, Set]:
        """Build whitelists for strict citation matching."""
        doc_whitelist = set()
        term_whitelist = set()

        # Add document names from refined_outputs/ (STRICT - no fallback)
        for md_file in self.outputs_dir.rglob('*.md'):
            doc_name = md_file.stem
            doc_whitelist.add(doc_name)
            doc_whitelist.add(doc_name.replace('_', ''))
            doc_whitelist.add(doc_name.replace('-', ''))

        # Add glossary terms
        for entity in glossary.get('entities', []):
            entity_id = entity.get('id', '')
            name = entity.get('name', '')
            aliases = entity.get('aliases', [])

            if entity_id:
                term_whitelist.add(entity_id.lower())
            if name:
                term_whitelist.add(name.lower())

            for alias in aliases:
                if alias:
                    term_whitelist.add(alias.lower())

        return doc_whitelist, term_whitelist

    def build_taxonomy_index(self, glossary: dict) -> Tuple[List, List, List]:
        """Build taxonomy index from glossary for entity matching."""
        tooling_types = []
        processes = []
        doc_types = []

        for entity in glossary.get('entities', []):
            entity_id = entity.get('id', '')
            name = entity.get('name', '')
            category = entity.get('category', '')
            aliases = entity.get('aliases', [])
            tags = entity.get('tags', [])
            is_process = entity.get('is_process', False)
            is_root = entity.get('is_root', False)
            is_doc_type = '文档类型' in category or '管理制度' in category or '技术规范' in category

            keywords = set()
            keywords.add(name)
            for alias in aliases:
                keywords.add(alias)
                if len(alias) >= 2:
                    keywords.add(alias[:2])
            for tag in tags:
                keywords.add(tag)

            entity_data = {
                'id': entity_id,
                'name': name,
                'category': category,
                'aliases': aliases,
                'tags': tags,
                'keywords': list(keywords),
                'definition': entity.get('definition', ''),
            }

            if is_process:
                processes.append(entity_data)
            elif is_doc_type:
                doc_types.append(entity_data)
            elif entity_id and (entity_id.endswith('_Tooling') or
                                '工装类型' in category or
                                '工装' in name):
                tooling_types.append(entity_data)
            elif '工装' in name and not is_root:
                tooling_types.append(entity_data)

        return tooling_types, processes, doc_types

    def extract_official_references(self, content: str) -> dict:
        """Extract official references from document structure fields."""
        cites = []
        forms = []

        lines = content.split('\n')
        in_references_section = False
        in_tables_section = False

        for line in lines:
            line_stripped = line.strip()

            if re.search(r'^\d+\s*规范性引用文件|^-\s*\d+\s*规范性引用文件', line_stripped):
                in_references_section = True
                in_tables_section = False
                continue
            elif re.search(r'^\d+\s*表格|^-\s*\d+\s*表格', line_stripped):
                in_tables_section = True
                in_references_section = False
                continue
            elif re.match(r'^\d+\s*', line_stripped) and '表格' not in line_stripped and '引用' not in line_stripped:
                in_references_section = False
                in_tables_section = False

            if not line_stripped or line_stripped.startswith('#'):
                continue

            if in_references_section:
                for doc_type, pattern in code_patterns(self.doc_prefixes).items():
                    matches = re.findall(pattern, line_stripped, re.IGNORECASE)
                    for match in matches:
                        full_code = f"{doc_type}{match}"
                        normalized = self.normalize_doc_code(full_code)
                        if normalized not in cites:
                            cites.append(normalized)

            elif in_tables_section:
                form_prefix = self.doc_prefixes['form']
                form_matches = re.findall(re.escape(form_prefix) + r'\s*(\d{4}-\d+)', line_stripped, re.IGNORECASE)
                for match in form_matches:
                    normalized = self.normalize_doc_code(f"{form_prefix}{match}")
                    if normalized not in forms:
                        forms.append(normalized)

        return {'cites': cites, 'forms': forms}

    def extract_strict_citations(self, content: str, doc_whitelist: Set,
                                 term_whitelist: Set) -> List[Dict]:
        """Extract valid citations using strict whitelist filtering."""
        citations = []

        # Pattern 1: WikiLinks [[...]]
        wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
        for link in wikilinks:
            link_clean = link.strip()
            if len(link_clean) < 2:
                continue
            link_normalized = link_clean.replace('.md', '').replace('_', '').replace('-', '')
            if link_clean in doc_whitelist or link_normalized in doc_whitelist:
                citations.append({
                    'type': 'wikilink',
                    'target': link_clean,
                    'valid': True
                })

        # Pattern 2: Book titles 《...》
        book_titles = re.findall(r'《([^》]+)》', content)
        for title in book_titles:
            if len(title) >= 2:
                citations.append({
                    'type': 'booktitle',
                    'target': title,
                    'valid': True
                })

        return citations

    def extract_doc_relationships(self, content: str, doc_name: str,
                                   doc_whitelist: Set) -> List[Dict]:
        """Extract document-to-document relationships."""
        relationships = []

        cite_patterns = [
            r'参照[《\[]([^》\]]+)[》\]]',
            r'执行[《\[]([^》\]]+)[》\]]',
            r'依据[《\[]([^》\]]+)[》\]]',
            r'适用于[《\[]([^》\]]+)[》\]]',
        ]

        for pattern in cite_patterns:
            matches = re.findall(pattern, content)
            for target in matches:
                target = target.strip()
                if len(target) >= 2:
                    relationships.append({
                        'type': 'Cites',
                        'target': target,
                        'direction': 'forward'
                    })

        number_pattern = r'^([A-Z]+/[A-Z0-9]+-\d+)(-\d+)+'
        doc_stem = Path(doc_name).stem
        match = re.match(number_pattern, doc_stem)
        if match:
            base编号 = match.group(1)
            relationships.append({
                'type': 'Parent',
                'target': base编号,
                'direction': 'upward'
            })

        return relationships

    def detect_doc_type(self, content: str, doc_types: List) -> str:
        """Detect document type from content."""
        doc_type_scores = defaultdict(int)

        for doc_type in doc_types:
            for keyword in doc_type['keywords']:
                if len(keyword) >= 2:
                    count = content.lower().count(keyword.lower())
                    doc_type_scores[doc_type['id']] += count

        if doc_type_scores:
            best_id = max(doc_type_scores.items(), key=lambda x: x[1])[0]
            return best_id

        return '通用文档'

    def analyze_document(self, doc_path: Path, tooling_types: List, processes: List,
                        doc_types: List, doc_whitelist: Set,
                        term_whitelist: Set) -> Dict:
        """Analyze a document and determine which entities it relates to."""
        with open(doc_path, 'r', encoding='utf-8') as f:
            content = f.read()

        content_lower = content.lower()
        doc_name = doc_path.name

        title = ''
        summary = ''
        version = ''

        if content.startswith('﻿'):
            content = content[1:]

        if content.startswith('---'):
            end_idx = content.find('---', 3)
            if end_idx > 0:
                frontmatter = content[3:end_idx]
                title_match = re.search(r'title:\s*(.+)$', frontmatter, re.MULTILINE)
                if title_match:
                    title = title_match.group(1).strip()
                version_match = re.search(r'version:\s*"?([^"\n]+)"?', frontmatter)
                if version_match:
                    version = version_match.group(1).strip()

        paragraphs = content.split('\n\n')
        for para in paragraphs:
            para = para.strip()
            if len(para) > 50 and not para.startswith('#'):
                summary = para[:200] + '...' if len(para) > 200 else para
                break

        citations = self.extract_strict_citations(content, doc_whitelist, term_whitelist)
        valid_citations = [c for c in citations if c['valid']]
        doc_relationships = self.extract_doc_relationships(content, doc_name, doc_whitelist)
        official_refs = self.extract_official_references(content)

        for ref in official_refs['cites']:
            doc_relationships.append({
                'type': 'Cites',
                'target': ref,
                'source': 'official_reference',
                'direction': 'forward'
            })

        for form in official_refs['forms']:
            doc_relationships.append({
                'type': 'Parent-Child',
                'target': form,
                'source': 'official_table',
                'direction': 'downward'
            })

        type_scores = defaultdict(lambda: {'score': 0, 'matches': []})

        for tool in tooling_types:
            total_score = 0
            matches = []

            for keyword in tool['keywords']:
                if len(keyword) < 2:
                    continue
                if keyword in title:
                    total_score += 10
                    matches.append(f"标题含'{keyword[:6]}'")

            for keyword in tool['keywords']:
                if len(keyword) < 2:
                    continue
                count = content_lower.count(keyword.lower())
                if count > 0:
                    points = min(count * 2, 20)
                    total_score += points
                    if count <= 3:
                        matches.append(f"正文'{keyword[:4]}'出现{count}次")

            for tag in tool.get('tags', []):
                if len(tag) >= 2 and tag in content_lower:
                    count = content_lower.count(tag.lower())
                    if count > 0:
                        total_score += min(count * 3, 15)

            if total_score > 0:
                type_scores[tool['id']] = {
                    'id': tool['id'],
                    'name': tool['name'],
                    'score': total_score,
                    'matches': matches[:5],
                    'definition': tool.get('definition', '')
                }

        sorted_types = sorted(type_scores.values(), key=lambda x: x['score'], reverse=True)

        related_processes = []
        for proc in processes:
            for keyword in proc.get('keywords', []):
                if len(keyword) < 2:
                    continue
                if keyword in title or keyword in content_lower:
                    related_processes.append({
                        'id': proc['id'],
                        'name': proc['name']
                    })
                    break

        detected_type = self.detect_doc_type(content, doc_types)

        valid_ids = [t['id'] for t in sorted_types[:5] if t.get('id') and t['id'].strip()]

        DOC_CODE_TO_PHASE = {
            '140701': '策划', '14070201': '申请', '14070202': '设计', '14070204': '验收',
            '14070301': '使用', '14070303': '维护', '14070304': '维护', '14070305': '使用',
            '140704': '验收', '140705': '优化',
        }

        doc_code_match = re.search(r'140(\d{3,5})', doc_name.upper())
        phase = ''
        if doc_code_match:
            code_suffix = '140' + doc_code_match.group(1)
            phase = DOC_CODE_TO_PHASE.get(code_suffix, '')

        if doc_name.upper().startswith(self.doc_prefixes['policy']):
            phase = '策划,申请,设计,制造,验收,使用,维护,优化'

        # D5-2: Apply aliases normalization to entities before returning
        normalized_ids = self.apply_aliases_to_entities(valid_ids)
        normalized_types = []
        for st in sorted_types[:5]:
            normalized_name = self.normalize_term(st.get('name', ''))
            normalized_id = self.normalize_term(st.get('id', ''))
            normalized_types.append({
                **st,
                'name': normalized_name,
                'id': normalized_id
            })

        return {
            'doc_name': doc_name,
            'doc_path': str(doc_path),
            'title': title,
            'summary': summary,
            'version': version,
            'doc_type': detected_type,
            'applicable_objects': normalized_ids,
            'object_details': normalized_types,
            'related_processes': related_processes[:3],
            'related_docs': doc_relationships,
            'citations': valid_citations,
            'official_references': official_refs,
            'confidence_score': sorted_types[0]['score'] if sorted_types else 0,
            'phase': phase,
            'extraction_version': 'v2_namespace'  # D5-3: Version tracking
        }

    # ==========================================================================
    # Heuristic Linking Methods (from map_knowledge.py)
    # ==========================================================================
    def infer_doc_level(self, doc_name: str, title: str = "") -> int:
        """Infer document level from filename patterns."""
        doc_name_upper = doc_name.upper()
        if doc_name_upper.startswith(self.doc_prefixes['policy']):
            return 0
        elif doc_name_upper.startswith(self.doc_prefixes['procedure']):
            return 1
        elif doc_name_upper.startswith(self.doc_prefixes['instruction']):
            return 2
        elif doc_name_upper.startswith(self.doc_prefixes['form']):
            return 3

        search_text = (doc_name + " " + title).lower()

        for pattern in LEVEL_PATTERNS[0]:
            if pattern.lower() in search_text:
                return 0

        for pattern in LEVEL_PATTERNS[3]:
            if pattern.lower() in search_text:
                return 3

        for pattern in LEVEL_PATTERNS[1]:
            if pattern.lower() in search_text:
                return 1

        for pattern in LEVEL_PATTERNS[2]:
            if pattern.lower() in search_text:
                return 2

        return 2

    def parse_doc_code(self, doc_name: str) -> str:
        """Extract document code from filename."""
        prefixes = '|'.join(re.escape(value) for value in sorted(self.doc_prefixes.values(), key=len, reverse=True))
        match = re.match(r'^(' + prefixes + r')(\d{4,8})', doc_name, re.IGNORECASE)
        if match:
            return match.group(1).upper() + match.group(2)
        return ''

    def find_best_parent_by_code(self, doc_code: str, all_doc_codes: Set) -> str:
        """Find best parent document based on coding rules."""
        if not doc_code:
            return ''

        base_code = doc_code
        if re.match(r'.*-\d{2}$', doc_code):
            base_code = doc_code.rsplit('-', 1)[0]

        candidates = []

        if doc_code.startswith(self.doc_prefixes['instruction']):
            procedure_code = self.doc_prefixes['procedure'] + doc_code[len(self.doc_prefixes['instruction']):]
            candidates.append((procedure_code, 'direct'))
            if base_code != doc_code:
                procedure_base = self.doc_prefixes['procedure'] + base_code[len(self.doc_prefixes['instruction']):]
                candidates.append((procedure_base, 'base'))

        elif doc_code.startswith(self.doc_prefixes['procedure']):
            offset = len(self.doc_prefixes['procedure'])
            if len(doc_code) >= offset + 2:
                policy_code = self.doc_prefixes['policy'] + doc_code[offset:offset + 2] + '07'
                candidates.append((policy_code, 'lift'))
                if len(doc_code) >= offset + 3:
                    policy_code2 = self.doc_prefixes['policy'] + doc_code[offset:offset + 3] + '07'
                    candidates.append((policy_code2, 'lift_4dig'))

        elif doc_code.startswith(self.doc_prefixes['policy']):
            return 'ROOT_SYSTEM'

        for candidate, rule_type in candidates:
            if candidate in all_doc_codes:
                return candidate

        return ''

    def build_heuristic_links(self, mappings: List[Dict]) -> Dict:
        """Build hierarchical tree structure using document code-based heuristics."""
        code_to_doc = {}
        doc_to_code = {}
        doc_name_normalized = {}

        for m in mappings:
            doc_name = m.get('doc_name', '')
            doc_code = self.parse_doc_code(doc_name)

            if doc_code:
                code_to_doc[doc_code] = doc_name
                doc_to_code[doc_name] = doc_code

            normalized = doc_name.replace('附件1：', '').replace('附件2：', '').replace('附件3：', '').replace('附件4：', '').replace('附件5：', '').replace('附件6：', '').replace('附件7：', '').replace('_', '').replace('-', '').replace(' ', '')
            doc_name_normalized[normalized] = doc_name

        all_doc_codes = set(code_to_doc.keys())

        form_to_parent = {}

        for m in mappings:
            doc_name = m.get('doc_name', '')
            official_refs = m.get('official_references', {})
            forms = official_refs.get('forms', [])

            for form_code in forms:
                form_code_normalized = form_code.replace('_', '').replace('-', '').replace(' ', '')

                for normalized_name, orig_name in doc_name_normalized.items():
                    if form_code_normalized in normalized_name or normalized_name in form_code_normalized:
                        form_to_parent[orig_name] = doc_name
                        break

        parent_links = {}
        link_types = {}

        for m in mappings:
            doc_name = m.get('doc_name', '')
            doc_code = self.parse_doc_code(doc_name)

            if not doc_code:
                continue

            related_docs = m.get('related_docs', [])
            has_explicit_parent = False

            for rel in related_docs:
                if rel.get('type') in ['Cites', 'Parent'] and rel.get('direction') == 'forward':
                    target = rel.get('target', '')
                    if any(x in target.upper() for x in [self.doc_prefixes['policy'], self.doc_prefixes['procedure']]):
                        has_explicit_parent = True
                        parent_links[doc_name] = target
                        link_types[doc_name] = 'explicit'
                        break

            if not has_explicit_parent:
                parent_code = self.find_best_parent_by_code(doc_code, all_doc_codes)

                if parent_code:
                    parent_doc = code_to_doc.get(parent_code, '')
                    if parent_doc:
                        parent_links[doc_name] = parent_doc
                        link_types[doc_name] = 'heuristic'

        for form_doc, parent_doc in form_to_parent.items():
            if form_doc not in parent_links:
                parent_links[form_doc] = parent_doc
                link_types[form_doc] = 'official_form'

        root_children = []

        for m in mappings:
            doc_name = m.get('doc_name', '')
            title = m.get('title', '')
            level = self.infer_doc_level(doc_name, title)

            if doc_name not in parent_links:
                if level in [0, 1]:
                    parent_links[doc_name] = 'ROOT_SYSTEM'
                    link_types[doc_name] = 'heuristic'
                    root_children.append(doc_name)

        return {
            'parent_doc': parent_links,
            'root_children': list(set(root_children)),
            'link_type': link_types
        }

    def apply_heuristic_links(self, mappings: List[Dict], heuristic_links: Dict) -> List[Dict]:
        """Apply heuristic links to mappings and add parent_doc field."""
        parent_doc_map = heuristic_links.get('parent_doc', {})
        link_type_map = heuristic_links.get('link_type', {})

        for m in mappings:
            doc_name = m.get('doc_name', '')

            if doc_name in parent_doc_map:
                parent = parent_doc_map[doc_name]
                if parent != 'ROOT_SYSTEM':
                    m['parent_doc'] = parent
                else:
                    m['parent_doc'] = None

                m['link_type'] = link_type_map.get(doc_name, 'unknown')
            else:
                m['parent_doc'] = None
                m['link_type'] = 'none'

        return mappings

    # ==========================================================================
    # Graph Integrity Validator (from map_knowledge.py)
    # ==========================================================================
    class GraphIntegrityValidator:
        """Validates knowledge graph integrity before writing to disk."""

        def __init__(self, mappings: List[Dict], heuristic_links: Dict):
            self.mappings = mappings
            self.heuristic_links = heuristic_links
            self.errors = []
            self.warnings = []
            self._builder = None

        @property
        def builder(self):
            if self._builder is None:
                self._builder = GraphBuilder()
            return self._builder

        def validate(self) -> bool:
            """Run all validation checks. Returns True if valid."""
            node_names = set()
            for m in self.mappings:
                doc_name = m.get('doc_name', '')
                if doc_name:
                    node_names.add(doc_name)

            node_names.add('ROOT_SYSTEM')

            self._check_node_completeness(node_names)
            self._check_edge_integrity(node_names)
            self._check_level_consistency()
            self._detect_orphans(node_names)
            self._detect_dangling_references(node_names)

            if self.errors:
                return False

            return True

        def _check_node_completeness(self, node_names: Set):
            """Check if all referenced nodes exist."""
            parent_doc_map = self.heuristic_links.get('parent_doc', {})

            for child, parent in parent_doc_map.items():
                if parent and parent != 'ROOT_SYSTEM':
                    if parent in node_names:
                        continue
                    self.warnings.append(
                        f"Parent node '{parent}' not found in mappings "
                        f"(referenced by '{child}')"
                    )

        def _check_edge_integrity(self, node_names: Set):
            """Check if all parent-child relationships are closed."""
            parent_doc_map = self.heuristic_links.get('parent_doc', {})

            for child, parent in parent_doc_map.items():
                if not parent:
                    self.errors.append(
                        f"Node '{child}' has no parent assigned"
                    )

        def _check_level_consistency(self):
            """Check if level hierarchy is consistent."""
            parent_doc_map = self.heuristic_links.get('parent_doc', {})

            for child, parent in parent_doc_map.items():
                if parent == 'ROOT_SYSTEM':
                    continue

                child_code = self.builder.parse_doc_code(child)
                parent_code = self.builder.parse_doc_code(parent)

                if not child_code or not parent_code:
                    continue

                child_level = self.builder.infer_doc_level(child)
                parent_level = self.builder.infer_doc_level(parent)

                if child_level <= parent_level:
                    self.warnings.append(
                        f"Level inconsistency: '{child}' (L{child_level}) -> '{parent}' (L{parent_level})"
                    )

        def _detect_orphans(self, node_names: Set):
            """Detect orphan nodes without any connections."""
            parent_doc_map = self.heuristic_links.get('parent_doc', {})

            children = set(parent_doc_map.keys())
            parents = set(parent_doc_map.values())
            parents.discard('ROOT_SYSTEM')

            orphans = []
            for node in node_names:
                if node == 'ROOT_SYSTEM':
                    continue
                if node not in children and node not in parents:
                    orphans.append(node)

            if orphans:
                self.warnings.append(f"Found {len(orphans)} orphan nodes without connections")

        def _detect_dangling_references(self, node_names: Set):
            """Detect dangling references."""
            dangling_refs = []

            for m in self.mappings:
                doc_name = m.get('doc_name', '')
                related_docs = m.get('related_docs', [])

                for rel in related_docs:
                    target = rel.get('target', '')
                    if not target:
                        continue
                    target_normalized = target.replace('_', '').replace('-', '').replace(' ', '')
                    exists = False
                    for node in node_names:
                        node_normalized = node.replace('_', '').replace('-', '').replace(' ', '')
                        if (target_normalized in node_normalized or
                            node_normalized in target_normalized):
                            exists = True
                            break
                    if not exists and target != 'ROOT_SYSTEM':
                        dangling_refs.append({
                            'source': doc_name,
                            'target': target
                        })

            if dangling_refs:
                self.warnings.append(f"Found {len(dangling_refs)} dangling references")

    # ==========================================================================
    # Main Entry Point
    # ==========================================================================
    def build_graph(self) -> Dict:
        """Execute complete knowledge graph building workflow.

        Returns:
            Dict with build results
        """
        print("=" * 60)
        print("GraphBuilder - Knowledge Mapping")
        print("=" * 60)

        # Load glossary
        glossary = self.load_glossary()

        # Build whitelists
        doc_whitelist, term_whitelist = self.build_whitelists(glossary)

        # Build taxonomy index
        tooling_types, processes, doc_types = self.build_taxonomy_index(glossary)

        # Find markdown files from refined_outputs (STRICT)
        md_files = []
        for f in self.outputs_dir.rglob('*.md'):
            path_str = str(f)
            if any(x in path_str for x in ['/concepts/', '/.git/', '/transformation/', '/dist/']):
                continue
            md_files.append(f)

        md_files.sort()

        # Analyze each document
        mappings = []
        for doc_path in md_files:
            try:
                result = self.analyze_document(
                    doc_path, tooling_types, processes, doc_types,
                    doc_whitelist, term_whitelist
                )
                mappings.append(result)
            except Exception as e:
                print(f"[WARN] {doc_path.name}: {e}")

        # Filter to documents with applicable objects
        valid_mappings = [m for m in mappings if m['applicable_objects']]

        # Build heuristic links
        heuristic_links = self.build_heuristic_links(valid_mappings)
        valid_mappings = self.apply_heuristic_links(valid_mappings, heuristic_links)

        # Build output
        output = {
            'version': 'v2.2',
            'generated_at': datetime.now().isoformat(),
            'source': 'glossary.yaml + outputs/',
            'description': 'Knowledge mapping with heuristic hierarchical linking',
            'stats': {
                'total_docs_scanned': len(md_files),
                'docs_with_mappings': len(valid_mappings),
                'tooling_types_count': len(tooling_types),
                'processes_count': len(processes),
                'heuristic_links_created': sum(1 for t in heuristic_links.get('link_type', {}).values() if t == 'heuristic'),
            },
            'mappings': valid_mappings,
            'taxonomy_index': {
                'tooling_types': tooling_types,
                'processes': processes
            },
            'heuristic_links': heuristic_links
        }

        # Run validator
        validator = self.GraphIntegrityValidator(valid_mappings, heuristic_links)
        if not validator.validate():
            print("[WARN] Graph validation found issues")

        # Save output
        self.dist_dir.mkdir(exist_ok=True)
        output_file = self.dist_dir / 'knowledge_map.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n[OK] Knowledge map saved to: {output_file}")
        return output
