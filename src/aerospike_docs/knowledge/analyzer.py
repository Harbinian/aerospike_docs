# -*- coding: utf-8 -*-
"""Knowledge Analyzer Domain Service.

Encapsulates logic from:
- scripts/lifecycle_audit.py (lifecycle elements)
- scripts/map_sql_lineage.py (SQL lineage tracking)
"""

import json
import re
import time
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Logger
from aerospike_docs.core.logging import get_logger
logger = get_logger(__name__)


# API Configuration
from aerospike_docs.core.config import MINIMAX_MODEL_NAME

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_API_URL = os.environ.get(
    "MINIMAX_API_URL",
    "https://api.minimax.chat/v1/text/chatcompletion_v2"
)
# Model name loaded from environment via core.config (12-Factor pattern)

# 36 baseline SQL fields
BASELINE_FIELDS = [
    '工装名称', '工装图号', '序列号', '原样工装序列号', '制造日期', '制造版次',
    '制造派工号', '制造商', '定检属性', '定检周期', '重量kg', '配备吊环',
    '配备叉孔', '主体材质', '库位', '主体长度', '主体宽度', '主体高度',
    '分体数量', '当前版次', '定检有效截止', '定检技术要求', '应用历史',
    '封存方式', '可用状态', '机型', '分工状态', '受控工装', '产品图号',
    '定检有效期剩余天', '定检派工状态', '套数号', '变更单编号', '通用类型',
    '产权所有', '工装有效状态'
]

# LLM Prompt for lifecycle elements extraction
LIFECYCLE_PROMPT = """你是一个航空架构师。请阅读以下文档内容，严格提取工装全生命周期中的【必要字段】、【里程碑】和【输出物】。

## 请结合上下文语义理解，返回 JSON 格式：
{{"essential_fields": [{{"name": "字段名", "description": "字段描述"}}], "milestones": [{{"phase": "阶段", "name": "里程碑名称", "description": "描述"}}], "outputs": [{{"name": "输出物名称", "code": "表格代码", "type": "类型"}}]}}

## 极其严格的排除规则（防幻觉与脏数据）
1. 严禁提取文档结构词：绝对不允许将文档的章节标题（如"1. 目的"、"2. 范围"、"3. 术语和定义"、"4. 职责与权限"）作为字段、里程碑或输出物提取！如有发现，直接剔除。
2. 严格定义输出物：输出物 (outputs) 必须是具体的、可交付的业务凭证，例如：带编号的表单（如 FORM1407-xx）、验收报告、图纸、台账记录或实物凭证。
3. 格式清洗：提取的文本必须纯净，严禁带有 Markdown 标号前缀（如 "#"、"1."、"4.1" 或 "/ .4" 等无意义标点）。

## 重要约束
1. 若无对应内容，请返回空列表 {{"essential_fields": [], "milestones": [], "outputs": []}}
2. 只提取与工装全生命周期直接相关的要素
3. 不要猜测或推断，只提取文档中明确存在的内容

## 文档内容：
{content}

仅返回 JSON，不要有其他内容。
"""


class KnowledgeAnalyzer:
    """Domain Service for knowledge analysis (lifecycle & lineage).

    Extracts logic from lifecycle_audit.py and map_sql_lineage.py.
    """

    def __init__(self, project_root: Path = None):
        """Initialize KnowledgeAnalyzer.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root or Path.cwd()
        self.outputs_dir = self.project_root / "outputs"
        self.dist_dir = self.project_root / "dist"
        self.reports_dir = self.dist_dir / "reports"

    # ==========================================================================
    # Lifecycle Audit Methods (from lifecycle_audit.py)
    # ==========================================================================
    def call_llm_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Call Minimax API for extraction."""
        if not MINIMAX_API_KEY:
            return None

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
            print(f"    [API 错误] {e}")

        return None

    def clean_dirty_data(self, items: List[Dict[str, Any]], field_name: str = "name") -> List[Dict]:
        """Clean dirty data from extracted items."""
        dirty_keywords = ["术语", "定义", "范围", "目的", "职责", "权限"]

        cleaned = []
        for item in items:
            value = item.get(field_name, "")
            if any(kw in value for kw in dirty_keywords) and len(value) < 8:
                continue
            if re.match(r'^[\d\.#\/\-\s]+', value):
                continue
            cleaned.append(item)

        return cleaned

    def parse_llm_response(self, result: str) -> Dict[str, Any]:
        """Parse LLM response into structured data."""
        elements = {
            "essential_fields": [],
            "milestones": [],
            "outputs": []
        }

        try:
            cleaned = re.sub(r'^```json\s*', '', result.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r'\s*```$', '', cleaned)

            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                json_obj = json.loads(json_match.group(0))
                elements["essential_fields"] = self.clean_dirty_data(
                    json_obj.get("essential_fields", []), "name"
                )
                elements["milestones"] = self.clean_dirty_data(
                    json_obj.get("milestones", []), "name"
                )
                elements["outputs"] = self.clean_dirty_data(
                    json_obj.get("outputs", []), "name"
                )

        except json.JSONDecodeError as e:
            print(f"    [JSON 解析错误] {e}")

        return elements

    def extract_lifecycle_elements(self, md_file: Path) -> Dict[str, Any]:
        """Extract lifecycle elements from a markdown file using LLM."""
        elements = {
            "fields": [],
            "milestones": [],
            "outputs": []
        }

        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read markdown file {md_file}: {e}")
            return elements

        title = md_file.stem
        code = ""
        if "_" in title:
            parts = title.split("_", 1)
            code = parts[0]
            title = parts[1] if len(parts) > 1 else title

        elements["title"] = title
        elements["code"] = code

        if not MINIMAX_API_KEY:
            return elements

        content_snippet = content[:8000]
        prompt = LIFECYCLE_PROMPT.format(content=content_snippet)

        result = self.call_llm_api(prompt)

        if result:
            llm_elements = self.parse_llm_response(result)

            for field in llm_elements.get("essential_fields", []):
                elements["fields"].append({
                    "name": field.get("name", ""),
                    "description": field.get("description", "")
                })

            for milestone in llm_elements.get("milestones", []):
                elements["milestones"].append({
                    "phase": milestone.get("phase", ""),
                    "name": milestone.get("name", ""),
                    "description": milestone.get("description", "")
                })

            for output in llm_elements.get("outputs", []):
                elements["outputs"].append({
                    "name": output.get("name", ""),
                    "code": output.get("code", ""),
                    "type": output.get("type", "表格")
                })

        return elements

    def run_lifecycle_audit(self) -> Dict:
        """Execute lifecycle audit workflow.

        Returns:
            Dict with audit results
        """
        print("=" * 60)
        print("KnowledgeAnalyzer - Lifecycle Audit")
        print("=" * 60)

        # Find PROC level documents
        main_docs = []
        if self.outputs_dir.exists():
            for item in self.outputs_dir.iterdir():
                if item.is_dir() and item.name.startswith("PROC"):
                    md_files = list(item.glob("*.md"))
                    if md_files:
                        main_docs.append(md_files[0])

        main_docs.sort(key=lambda x: x.stem)

        if not main_docs:
            print("[警告] 未找到 PROC 级别文档")
            return {"error": "No PROC documents found"}

        print(f"\n[信息] 开始处理 {len(main_docs)} 个文档...")

        all_elements = []
        for md_file in main_docs:
            elements = self.extract_lifecycle_elements(md_file)
            elements["file"] = str(md_file.relative_to(self.project_root))
            all_elements.append(elements)

        # Generate report
        report_lines = [
            "# 全生命周期业务要素审计报告 (LLM v2.0)",
            "",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"审计文档数: {len(all_elements)}",
            f"提取方式: LLM语义提取",
            "",
            "---",
            "",
        ]

        stages = [
            ("1. 策划与申请", ["策划", "申请"]),
            ("2. 设计与评审", ["设计", "评审"]),
            ("3. 制造与验收", ["制造", "验收"]),
            ("4. 交付与使用", ["交付", "使用"]),
            ("5. 维护与定检", ["维护", "保养", "定检", "校准"]),
            ("6. 转移与借用", ["转移", "借用"]),
            ("7. 返工与优化", ["返工", "优化"]),
        ]

        for stage_name, keywords in stages:
            report_lines.append(f"## {stage_name}")
            report_lines.append("")

            stage_docs = []
            for elem in all_elements:
                for kw in keywords:
                    milestones = elem.get("milestones", [])
                    if any(m.get("name", "").find(kw) >= 0 for m in milestones):
                        stage_docs.append(elem)
                        break

            if stage_docs:
                report_lines.append("| 字段 | 里程碑 | 输出物 |")
                report_lines.append("|------|--------|--------|")

                for doc in stage_docs:
                    doc_milestones = []
                    for kw in keywords:
                        for m in doc.get("milestones", []):
                            if m.get("name", "").find(kw) >= 0:
                                doc_milestones.append(m.get("name", ""))

                    outputs = doc.get("outputs", [])
                    output_names = [o.get("name", "")[:30] for o in outputs[:3]]

                    if doc_milestones or output_names:
                        fields = [f.get("description", "")[:20] for f in doc.get("fields", [])[:2]]
                        fields_str = " / ".join(fields) if fields else "-"
                        miles_str = " / ".join(doc_milestones[:2]) if doc_milestones else "-"
                        out_str = " / ".join(output_names) if output_names else "-"

                        report_lines.append(f"| {fields_str} | {miles_str} | {out_str} |")

                report_lines.append("")
            else:
                report_lines.append("*该阶段暂无文档覆盖*")
                report_lines.append("")

        report_lines.extend([
            "---",
            "",
            "## 统计摘要",
            "",
            f"- 审计文档总数: {len(all_elements)}",
            f"- 涉及输出物总数: {sum(len(e.get('outputs', [])) for e in all_elements)}",
            f"- 涉及里程碑总数: {sum(len(e.get('milestones', [])) for e in all_elements)}",
            f"- 涉及字段总数: {sum(len(e.get('fields', [])) for e in all_elements)}",
            "",
        ])

        # Save report
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = self.reports_dir / "lifecycle_elements_audit.md"

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))

        print(f"Report generated: {report_file}")

        return {
            "total_docs": len(all_elements),
            "report_file": str(report_file)
        }

    # ==========================================================================
    # SQL Lineage Methods (from map_sql_lineage.py)
    # ==========================================================================
    def load_knowledge_map(self) -> dict:
        """Load knowledge_map.json."""
        km_path = self.dist_dir / "knowledge_map.json"
        if not km_path.exists():
            return {}

        with open(km_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_target_documents(self, knowledge_map: dict) -> List[dict]:
        """Get target FORM documents."""
        targets = []

        for item in knowledge_map.get('mappings', []):
            doc_type = item.get('doc_type', '')
            if doc_type in ['Doc_Form', 'Doc_Standard', 'Doc_Procedure']:
                doc_path = item.get('doc_path', '')
                doc_name = item.get('doc_name', '')
                if 'FORM' in doc_name or 'front_matter' in doc_name or '附件' in doc_name:
                    if doc_path:
                        doc_path_normalized = doc_path.replace('\\', '/')
                        if 'english_backup' not in doc_path_normalized:
                            targets.append({
                                'doc_name': doc_name,
                                'doc_path': doc_path,
                                'doc_type': doc_type
                            })

        # Also check attachments directory
        if self.outputs_dir.exists():
            for subdir in self.outputs_dir.iterdir():
                if subdir.is_dir():
                    attachments_subdir = subdir / "attachments"
                    if attachments_subdir.exists():
                        for md_file in attachments_subdir.glob("*.md"):
                            if 'FORM' in md_file.name or '附件' in md_file.name:
                                targets.append({
                                    'doc_name': md_file.name,
                                    'doc_path': str(md_file),
                                    'doc_type': 'Doc_Form'
                                })

        # Deduplicate
        seen = set()
        unique_targets = []
        for t in targets:
            key = t['doc_path']
            if key not in seen:
                seen.add(key)
                unique_targets.append(t)

        return unique_targets

    def extract_fields_from_document(self, doc_name: str, doc_content: str) -> List[Dict]:
        """Extract fields from document using LLM."""
        if not doc_content:
            return []

        prompt = f"""你是一个航空制造数据架构师。
请仔细阅读以下表单/文档内容，识别并列出该表单中所有需要填写的数据项字段。
只返回表单中实际存在的字段，不要推测不存在的字段。

严格返回 JSON 数组，格式：[{{"field": "字段名", "evidence": "在表单中的原始表头或标签"}}]。
如果表单中没有明确的数据项字段，返回 []。

文档名称：{doc_name}
---
文档内容：
{doc_content[:6000]}
---
"""

        for attempt in range(3):
            result = self.call_llm_api(prompt, timeout=60)
            if result:
                fields = self._parse_llm_json_response(result)
                if fields:
                    return fields
            time.sleep(1)

        return []

    def _parse_llm_json_response(self, response: str) -> List[Dict]:
        """Parse LLM JSON response."""
        try:
            cleaned = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r'```$', '', cleaned.strip(), flags=re.MULTILINE)

            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and 'fields' in result:
                return result.get('fields', [])
            return []
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
        return []

    def match_with_baseline(self, discovered_fields: List[Dict]) -> List[Dict]:
        """Match discovered fields with baseline fields."""
        matched = []

        for item in discovered_fields:
            field_name = item.get('field', '').strip()
            evidence = item.get('evidence', '')

            if not field_name:
                continue

            matched_field = None
            for baseline in BASELINE_FIELDS:
                if field_name == baseline:
                    matched_field = baseline
                    break
                if baseline in field_name or field_name in baseline:
                    matched_field = baseline
                    break
                baseline_clean = baseline.replace('kg', '').replace('(kg)', '').strip()
                field_clean = field_name.replace('kg', '').replace('(kg)', '').strip()
                if baseline_clean == field_clean:
                    matched_field = baseline
                    break

            if matched_field:
                matched.append({
                    'field': matched_field,
                    'original_field': field_name,
                    'evidence': evidence,
                    'action': 'DISCOVERED'
                })

        return matched

    def run_sql_lineage_analysis(self, max_docs: int = 5) -> Dict:
        """Execute SQL lineage analysis workflow.

        Args:
            max_docs: Maximum number of documents to process

        Returns:
            Dict with analysis results
        """
        print("=" * 60)
        print("KnowledgeAnalyzer - SQL Lineage Analysis")
        print("=" * 60)

        knowledge_map = self.load_knowledge_map()
        if not knowledge_map:
            print("[错误] 无法加载知识图谱")
            return {"error": "Knowledge map not found"}

        target_docs = self.get_target_documents(knowledge_map)
        print(f"找到 {len(target_docs)} 个目标文档")

        test_docs = target_docs[:max_docs]
        print(f"将处理 {len(test_docs)} 个文档...")

        field_matches = {field: [] for field in BASELINE_FIELDS}

        for idx, doc in enumerate(test_docs, 1):
            doc_name = doc.get('doc_name', '未知')
            doc_path = doc.get('doc_path', '')

            print(f"  [{idx}/{len(test_docs)}] 处理: {doc_name[:40]}...")

            try:
                path = Path(doc_path)
                if not path.exists():
                    continue
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read(8000)
            except Exception as e:
                logger.warning(f"Failed to read document {doc_path}: {e}")
                continue

            discovered = self.extract_fields_from_document(doc_name, content)
            matched = self.match_with_baseline(discovered)

            for item in matched:
                field = item.get('field', '')
                if field in field_matches:
                    item['doc_name'] = doc_name
                    field_matches[field].append(item)

            print(f"    发现 {len(discovered)} 个字段，匹配基准 {len(matched)} 个")

        # Generate report
        report_lines = [
            "# SQL 字段血缘追踪报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**基准字段数**: {len(BASELINE_FIELDS)}",
            "",
            "## 字段合规性检查结果",
            "",
            "| 数据库字段 | 合规状态 | 业务源头(文档名) | 操作 | 原文依据 |",
            "|:-----------|:---------|:-----------------|:-----|:---------|",
        ]

        for field in BASELINE_FIELDS:
            matches = field_matches.get(field, [])

            if not matches:
                report_lines.append(f"| {field} | 🔴 制度缺失(野生字段) | - | - | - |")
            else:
                first_match = matches[0]
                doc_name = first_match.get('doc_name', '未知')
                action = first_match.get('action', 'UNKNOWN')
                evidence = first_match.get('evidence', '')[:50]

                report_lines.append(f"| {field} | 🟢 制度覆盖 | {doc_name} | {action} | {evidence} |")

        covered = sum(1 for f in BASELINE_FIELDS if field_matches.get(f))
        orphan = len(BASELINE_FIELDS) - covered

        report_lines.extend([
            "",
            "## 统计摘要",
            "",
            f"- **制度覆盖字段数**: {covered} ({covered/len(BASELINE_FIELDS)*100:.1f}%)",
            f"- **野生字段数**: {orphan} ({orphan/len(BASELINE_FIELDS)*100:.1f}%)",
            "",
        ])

        if orphan > 0:
            orphan_fields = [f for f in BASELINE_FIELDS if not field_matches.get(f)]
            report_lines.extend([
                "## ⚠️ 需整改的野生字段",
                "",
                "以下字段存在于物理数据库中，但在业务制度文档中完全缺失：",
                "",
            ])
            for f in orphan_fields:
                report_lines.append(f"- {f}")
            report_lines.append("")

        # Save report
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = self.reports_dir / "sql_lineage_report.md"

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"报告已保存: {report_file}")
        print(f"\n✅ 物理表与业务体系打通！")
        print(f"  制度覆盖: {covered}/{len(BASELINE_FIELDS)} 字段")
        print(f"  野生字段: {orphan} 个")

        return {
            "covered": covered,
            "orphan": orphan,
            "report_file": str(report_file)
        }
