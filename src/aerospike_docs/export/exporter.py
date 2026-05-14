# -*- coding: utf-8 -*-
"""Data Exporter Domain Service.

Encapsulates logic from:
- scripts/export_to_system.py
- scripts/export_for_tooling_app.py
"""

import json
import yaml
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional, Callable
from collections import defaultdict


class DataExporter:
    """Domain Service for exporting glossary data to various formats.

    Integrates logic from export_to_system.py and export_for_tooling_app.py.
    """

    def __init__(self, project_root: Path = None,
                 glossary_validator_class: Optional[type] = None):
        """Initialize DataExporter.

        Args:
            project_root: Root directory of the project
            glossary_validator_class: Optional GlossaryValidator class for
                validation. If not provided, uses a simple file-exists check.
        """
        self.project_root = project_root or Path.cwd()
        self.glossary_path = self.project_root / "glossary.yaml"
        self.dist_dir = self.project_root / "dist"
        self._validator_class = glossary_validator_class

    def load_glossary(self) -> dict:
        """Load glossary.yaml."""
        with open(self.glossary_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def validate_glossary(self) -> bool:
        """Validate glossary before export.

        Returns:
            True if validation passes
        """
        # Try injected validator first
        if self._validator_class is not None:
            try:
                validator = self._validator_class(str(self.glossary_path))
                if hasattr(validator, 'load_file') and not validator.load_file():
                    return False
                result = validator.validate()
                return result.passed
            except Exception:
                pass

        # Try importing from Norms validation service (backward compatibility)
        try:
            from services.validation.validator import GlossaryValidator
            validator = GlossaryValidator(str(self.glossary_path))
            if not validator.load_file():
                return False
            result = validator.validate()
            return result.passed
        except ImportError:
            pass

        # Fallback: basic file existence and parse check
        if not self.glossary_path.exists():
            return False
        try:
            self.load_glossary()
            return True
        except Exception:
            return False

    def slugify(self, text: str) -> str:
        """Convert text to slug format."""
        slug = re.sub(r'[^a-zA-Z0-9]', '_', text)
        slug = re.sub(r'_+', '_', slug)
        return slug.upper().strip('_')

    def categorize_entity(self, entity: dict) -> str:
        """Determine dict_key based on entity category."""
        category = entity.get('category', '')
        name = entity.get('name', '')

        category_mappings = {
            '工装模具': 'TOOLING_TYPE',
            '工装类型': 'TOOLING_TYPE',
            '模具类型': 'TOOLING_TYPE',
            '夹具类型': 'TOOLING_TYPE',
            '检测设备': 'INSPECTION_DEVICE',
            '检测测量': 'INSPECTION_DEVICE',
            '检验检测': 'INSPECTION_DEVICE',
            '质量管理': 'QUALITY_MANAGEMENT',
            '质量控制': 'QUALITY_MANAGEMENT',
            '航空制造': 'AEROSPACE_MFG',
            '特种工艺': 'SPECIAL_PROCESS',
            '组织机构': 'ORGANIZATION',
            '人员角色': 'PERSONNEL_ROLE',
            '工装管理': 'TOOLING_MGMT',
            '工装设计': 'TOOLING_DESIGN',
            '工装分类': 'TOOLING_CATEGORY',
            '技术文件': 'TECHNICAL_DOC',
            '生产管理': 'PRODUCTION_MGMT',
            '设计规范': 'DESIGN_STANDARD',
            '分析验证': 'ANALYSIS_VERIFY',
        }

        for key, value in category_mappings.items():
            if key in category:
                return value

        keyword_mappings = {
            'C9': 'AIRCRAFT_MODEL',
            'QRA': 'AIRCRAFT_MODEL',
            '客户乙': 'AIRCRAFT_MODEL',
            '客户丙': 'AIRCRAFT_MODEL',
            'CUSTOMER_A': 'AIRCRAFT_MODEL',
            '工装': 'TOOLING_TYPE',
            '夹具': 'TOOLING_TYPE',
            '模具': 'TOOLING_TYPE',
            '检具': 'INSPECTION_DEVICE',
            '量具': 'INSPECTION_DEVICE',
            '质量': 'QUALITY_MANAGEMENT',
            '认证': 'CERTIFICATION',
            '标准': 'STANDARD_REF',
        }

        for keyword, dict_key in keyword_mappings.items():
            if keyword in name:
                return dict_key

        return 'GENERAL_TERMS'

    def build_dictionary_items(self, entities: List[dict]) -> Dict[str, List]:
        """Group entities into dictionary items (for system export)."""
        dictionaries = {}

        for entity in entities:
            aliases = entity.get('aliases', [])
            if any('__MERGE_TO__' in str(a) for a in aliases):
                continue

            term_id = entity.get('id', '')
            name = entity.get('name', '')
            category = entity.get('category', '')
            en_term = entity.get('en_term', '')

            if not name:
                continue

            dict_key = self.categorize_entity(entity)

            item = {
                'label': name,
                'value': term_id or self.slugify(name),
                'tags': [a for a in aliases if a and not a.startswith('__')][:5],
            }

            if en_term:
                item['en_label'] = en_term

            if dict_key not in dictionaries:
                dictionaries[dict_key] = []

            existing_values = {i.get('value') for i in dictionaries[dict_key]}
            if item['value'] not in existing_values:
                dictionaries[dict_key].append(item)

        return dictionaries

    def get_dict_description(self, dict_key: str) -> str:
        """Get description for dictionary key."""
        descriptions = {
            'TOOLING_TYPE': '工艺装备类型（工装、夹具、模具等）',
            'TOOLING_MGMT': '工装管理相关术语',
            'TOOLING_DESIGN': '工装设计相关术语',
            'TOOLING_CATEGORY': '工装分类术语',
            'INSPECTION_DEVICE': '检测设备与测量器具',
            'QUALITY_MANAGEMENT': '质量管理相关术语',
            'AEROSPACE_MFG': '航空制造相关术语',
            'SPECIAL_PROCESS': '特种工艺术语',
            'ORGANIZATION': '组织机构术语',
            'PERSONNEL_ROLE': '人员角色术语',
            'AIRCRAFT_MODEL': '飞机属性标签术语',
            'TECHNICAL_DOC': '技术文件术语',
            'PRODUCTION_MGMT': '生产管理术语',
            'DESIGN_STANDARD': '设计规范术语',
            'ANALYSIS_VERIFY': '分析与验证术语',
            'CERTIFICATION': '认证相关术语',
            'STANDARD_REF': '标准参考术语',
            'GENERAL_TERMS': '通用术语',
        }
        return descriptions.get(dict_key, dict_key.replace('_', ' ').title())

    def export_to_system(self) -> Dict:
        """Export to system initialization format.

        Returns:
            Dict with export results
        """
        print("=" * 60)
        print("DataExporter - Export to System")
        print("=" * 60)

        # Validate glossary first
        print("\n[0/3] Validating glossary...")
        if not self.validate_glossary():
            print("ERROR: Glossary validation failed!")
            return {"success": False, "error": "Validation failed"}

        # Load glossary
        print("\n[1/3] Loading glossary...")
        glossary = self.load_glossary()
        entities = glossary.get('entities', [])
        print(f"  - Total entities: {len(entities)}")

        # Build dictionaries
        print("[2/3] Building dictionaries...")
        dictionaries = self.build_dictionary_items(entities)
        print(f"  - Dictionaries created: {len(dictionaries)}")

        # Create output structure
        print("[3/3] Generating JSON...")

        output = {
            'version': datetime.now().strftime('%Y-%m-%d'),
            'generated_at': datetime.now().isoformat(),
            'source': 'glossary.yaml',
            'description': '工装系统术语字典初始化数据',
            'dictionaries': []
        }

        for dict_key in sorted(dictionaries.keys()):
            items = dictionaries[dict_key]
            items.sort(key=lambda x: x.get('label', ''))

            output['dictionaries'].append({
                'dict_key': dict_key,
                'dict_name': dict_key.replace('_', ' ').title(),
                'description': self.get_dict_description(dict_key),
                'item_count': len(items),
                'items': items
            })

        # Save JSON
        self.dist_dir.mkdir(exist_ok=True)
        output_file = self.dist_dir / 'tooling_system_init_data.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # Print summary
        total_items = sum(len(d['items']) for d in output['dictionaries'])

        print("\n" + "=" * 60)
        print("EXPORT SUMMARY")
        print("=" * 60)
        print(f"\n源文件:      glossary.yaml")
        print(f"输出文件:    {output_file}")
        print(f"版本:       {output['version']}")
        print(f"\n字典数量:   {len(output['dictionaries'])}")
        print(f"词条总数:   {total_items}")
        print("\n" + "=" * 60)

        return {"success": True, "output_file": str(output_file)}

    # ==========================================================================
    # Taxonomic Tree Export (from export_for_tooling_app.py)
    # ==========================================================================
    def build_taxonomy_tree(self, entities: List[dict]) -> List[Dict]:
        """Build taxonomy tree based on parent field."""
        roots = []
        children_by_parent = defaultdict(list)

        for entity in entities:
            if entity.get('is_process', False):
                continue

            entity_id = entity.get('id', '')
            name = entity.get('name', '')
            parent = entity.get('parent', '')
            aliases = entity.get('aliases', [])
            attributes = entity.get('attributes', {})
            is_root = entity.get('is_root', False)

            item = {
                'id': entity_id,
                'name': name,
                'aliases': [a for a in aliases if a != name][:5],
            }

            if attributes:
                item['attributes'] = attributes

            if is_root:
                roots.append(item)
            elif parent:
                children_by_parent[parent].append(item)

        # Build tree structure
        taxonomies = []
        for root in roots:
            subtypes = self._build_subtree(root['id'], children_by_parent)
            taxonomy = {
                'root': root['id'],
                'name': root['name'],
            }
            if root.get('aliases'):
                taxonomy['aliases'] = root['aliases']
            if root.get('attributes'):
                taxonomy['attributes'] = root['attributes']
            if subtypes:
                taxonomy['subtypes'] = subtypes
            taxonomies.append(taxonomy)

        return taxonomies

    def _build_subtree(self, parent_id: str, children_by_parent: dict) -> List[Dict]:
        """Recursively build subtype tree."""
        children = children_by_parent.get(parent_id, [])
        if not children:
            return []

        subtypes = []
        for child in children:
            subtype = {
                'id': child['id'],
                'name': child['name'],
            }
            if child.get('aliases'):
                subtype['aliases'] = child['aliases']
            if child.get('attributes'):
                subtype['attributes'] = child['attributes']

            sub_subtypes = self._build_subtree(child['id'], children_by_parent)
            if sub_subtypes:
                subtype['subtypes'] = sub_subtypes

            subtypes.append(subtype)

        return subtypes

    def extract_processes(self, entities: List[dict]) -> List[Dict]:
        """Extract process-related entities."""
        processes = []

        for entity in entities:
            if not entity.get('is_process', False):
                continue

            entity_id = entity.get('id', '')
            name = entity.get('name', '')
            aliases = entity.get('aliases', [])
            target_entity = entity.get('target_entity', '')
            flow_steps = entity.get('flow_steps', [])

            process = {
                'id': entity_id,
                'name': name,
            }
            if aliases:
                process['aliases'] = aliases
            if target_entity:
                process['target_entity'] = target_entity
            if flow_steps:
                process['flow_steps'] = flow_steps

            processes.append(process)

        return processes

    def extract_glossary(self, entities: List[dict]) -> List[Dict]:
        """Extract all entities as flat glossary."""
        glossary = []

        for entity in entities:
            entity_id = entity.get('id', '')
            name = entity.get('name', '')
            category = entity.get('category', '')
            en_term = entity.get('en_term', '')
            aliases = entity.get('aliases', [])
            description = entity.get('description', '')

            glossary.append({
                'id': entity_id,
                'name': name,
                'category': category,
                'en_term': en_term,
                'aliases': aliases,
                'description': description
            })

        return glossary

    def export_for_tooling_app(self) -> Dict:
        """Export to tooling app format.

        Returns:
            Dict with export results
        """
        print("=" * 60)
        print("DataExporter - Export for Tooling App")
        print("=" * 60)

        # Validate glossary first
        print("\n[0/4] Validating glossary...")
        if not self.validate_glossary():
            print("ERROR: Glossary validation failed!")
            return {"success": False, "error": "Validation failed"}

        # Load glossary
        print("\n[1/4] Loading glossary...")
        glossary = self.load_glossary()
        entities = glossary.get('entities', [])
        print(f"  - Total entities: {len(entities)}")

        # Build taxonomies
        print("[2/4] Building taxonomy tree...")
        taxonomies = self.build_taxonomy_tree(entities)
        print(f"  - Taxonomies: {len(taxonomies)}")

        # Count total nodes
        def count_nodes(items: List) -> int:
            count = len(items)
            for item in items:
                if 'subtypes' in item:
                    count += count_nodes(item['subtypes'])
            return count

        total_nodes = count_nodes(taxonomies)
        print(f"  - Total nodes: {total_nodes}")

        # Extract processes
        print("[3/4] Extracting processes...")
        processes = self.extract_processes(entities)
        print(f"  - Processes: {len(processes)}")

        # Extract full glossary
        full_glossary = self.extract_glossary(entities)

        # Build output
        output = {
            'version': datetime.now().strftime('%Y-%m-%d'),
            'generated_at': datetime.now().isoformat(),
            'source': 'glossary.yaml',
            'description': '工装系统主数据 - 支持级联菜单和流程导航',
            'metadata': {
                'total_entities': len(entities),
                'total_taxonomy_nodes': total_nodes,
                'total_processes': len(processes)
            },
            'taxonomies': taxonomies,
            'processes': processes,
            'glossary': full_glossary
        }

        # Save JSON
        self.dist_dir.mkdir(exist_ok=True)
        output_file = self.dist_dir / 'tooling_master_data.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # Print summary
        print("\n" + "=" * 60)
        print("EXPORT SUMMARY")
        print("=" * 60)
        print(f"\n输出文件: {output_file}")
        print(f"版本: {output['version']}")
        print(f"\n分类树: {len(taxonomies)} 个顶层")
        print(f"  - 总节点数: {total_nodes}")
        print(f"流程列表: {len(processes)} 个")
        print(f"术语词典: {len(full_glossary)} 条")
        print("\n" + "=" * 60)

        return {"success": True, "output_file": str(output_file)}

    # ==========================================================================
    # Main Export Method
    # ==========================================================================
    def export(self, target_type: str = "system") -> Dict:
        """Execute unified export interface.

        Args:
            target_type: Export target type ("system" or "tooling")

        Returns:
            Dict with export results
        """
        if target_type == "system":
            return self.export_to_system()
        elif target_type == "tooling":
            return self.export_for_tooling_app()
        else:
            return {"success": False, "error": f"Unknown export target: {target_type}"}
