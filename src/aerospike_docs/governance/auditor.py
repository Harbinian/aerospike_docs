# -*- coding: utf-8 -*-
"""Compliance Auditor Domain Service for role accountability audit."""

import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple

from aerospike_docs.core.config import MINIMAX_MODEL_NAME

MINIMAX_API_KEY = ""
MINIMAX_API_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"


class RateLimiter:
    """Simple rate limiter."""
    def __init__(self, max_calls=10, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def acquire(self):
        now = time.time()
        self.calls = [c for c in self.calls if now - c < self.period]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                self.calls = []
        self.calls.append(time.time())


rate_limiter = RateLimiter(max_calls=10, period=60)


def call_minimax_api(prompt: str, timeout: int = 120) -> Optional[str]:
    """Call Minimax API for text completion."""
    global MINIMAX_API_KEY
    if not MINIMAX_API_KEY:
        import os
        MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")

    if not MINIMAX_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MINIMAX_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "You are a professional aerospace manufacturing document analyst, expert in extracting structure and responsibility information from institutional documents."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 4096
    }

    try:
        rate_limiter.acquire()
        response = requests.post(
            MINIMAX_API_URL,
            headers=headers,
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        result = response.json()

        if result.get("choices") and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        return None

    except Exception as e:
        print(f"Minimax API error: {e}")
        return None


def llm_extract_tasks(document_name: str, content: str) -> List[Dict]:
    """Use LLM to extract tasks with department and role info."""
    lines = content.split('\n')
    section_5 = []
    section_7 = []
    in_section_5 = False
    in_section_7 = False

    for line in lines:
        line_clean = line.replace('\xa0', ' ')
        if re.match(r'^[-#]?\s*\d+\s*[\.\。]?\s*.{0,10}职责', line_clean):
            in_section_5 = True
            in_section_7 = False
            section_5.append(line_clean)
            continue
        if re.match(r'^[-#]?\s*7\s*[\.\。]?\s*.*?(?:流程|程序)', line_clean):
            in_section_7 = True
            in_section_5 = False
            section_7.append(line_clean)
            continue
        if in_section_5 and re.match(r'^[-#]?\s*[6六]\s*[\.\。]?', line_clean):
            in_section_5 = False
        if in_section_7 and re.match(r'^[-#]?\s*[8八]\s*[\.\。]?', line_clean):
            in_section_7 = False

        if in_section_5:
            section_5.append(line_clean)
        if in_section_7:
            section_7.append(line_clean)

    section_5_text = '\n'.join(section_5[:50])
    section_7_text = '\n'.join(section_7[:100])

    prompt = f"""Please analyze the following aerospace manufacturing institutional document and extract all tasks/actions with their responsibility information.

Document Name: {document_name}

【Section 5 - Organization and Responsibilities】
{section_5_text}

【Section 7 - Business Process】(if any)
{section_7_text}

Please output strictly according to this JSON Schema:
{{
  "tasks": [
    {{
      "action": "Action description (complete, e.g., Organize production unit to compile tooling variety table and conduct review)",
      "department": "Department (e.g., Technology Innovation Department. If not explicitly stated, use null)",
      "specific_role": "Specific role/position (e.g., Process Equipment Technician. If document only mentions department without specific position, use null)",
      "source": "section_5 or section_7"
    }}
  ]
}}

Important rules:
1. action must be complete, cannot be truncated
2. If document states "Technology Innovation Dept is responsible for X", department = "Technology Innovation Dept", specific_role = null
3. If document states "XX Technician is responsible for X", department can be null, specific_role = "XX Technician"
4. Only extract tasks with clear responsibility assignment
5. Ensure each action description is complete

Only output JSON, no other text."""

    result = call_minimax_api(prompt, timeout=180)

    if not result:
        return None

    try:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            data = json.loads(json_match.group())
            return data.get('tasks', [])
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")

    return None


class ComplianceAuditor:
    """Domain Service for role accountability compliance audit."""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.outputs_dir = self.project_root / "outputs"
        self.flowchart_path = self.project_root / "dist" / "flowchart_extractions.json"
        self.dist_dir = self.project_root / "dist"

    def load_flowchart_data(self) -> Dict[str, Dict[str, List[str]]]:
        if not self.flowchart_path.exists():
            print(f"Warning: Flowchart data not found at {self.flowchart_path}")
            return {}

        with open(self.flowchart_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        mapping = {}
        for extraction in data.get('extractions', []):
            doc_name = extraction.get('document', '')
            if not doc_name:
                continue

            mapping[doc_name] = {}
            for process in extraction.get('processes', []):
                process_name = process.get('process_name', '')
                actors = process.get('actors', [])
                if process_name:
                    mapping[doc_name][process_name] = actors

        print(f"Loaded flowchart data: {len(mapping)} documents")
        return mapping

    def grep_role_evidence_from_markdown(self, roles: Set[str]) -> Dict[str, List[Dict[str, str]]]:
        role_sources = {}

        if not self.outputs_dir.exists():
            return role_sources

        md_files = []
        for pattern in ["**/*.md", "**/*.MD"]:
            md_files.extend(self.outputs_dir.glob(pattern))

        md_files = [f for f in md_files if "english_backup" not in str(f) and "attachments" not in str(f)]

        print(f"[Grep Engine] Searching {len(md_files)} Markdown files for {len(roles)} roles...")

        for role in roles:
            found_evidence = []
            for md_file in md_files:
                if len(found_evidence) >= 2:
                    break

                try:
                    with open(md_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if role in line and len(line.strip()) > 10:
                                stripped = line.strip()
                                if len(stripped) > 10 and not stripped.startswith("#"):
                                    found_evidence.append({
                                        "doc": md_file.stem,
                                        "evidence": stripped[:200]
                                    })
                                    break
                except Exception:
                    continue

            if found_evidence:
                role_sources[role] = found_evidence

        print(f"[Grep Engine] Found evidence for {len(role_sources)} roles")
        return role_sources

    def find_matching_flowchart_doc(self, doc_path: str, flowchart_mapping: Dict) -> Optional[str]:
        parts = doc_path.split('\\')
        if parts:
            folder_name = parts[0]
            if folder_name in flowchart_mapping:
                return folder_name
            for key in flowchart_mapping.keys():
                if key.startswith(parts[0].split('_')[0]):
                    return key
        return None

    def find_flowchart_actors(self, doc_path: str, action: str, flowchart_mapping: Dict) -> List[str]:
        matched_doc = self.find_matching_flowchart_doc(doc_path, flowchart_mapping)
        if not matched_doc:
            return []

        processes = flowchart_mapping.get(matched_doc, {})

        if action in processes:
            return processes[action]

        for process_name, actors in processes.items():
            if action in process_name or process_name in action:
                return actors

        return []

    def analyze_document(self, doc_path: str, flowchart_mapping: Dict) -> Dict[str, Any]:
        full_path = self.outputs_dir / doc_path

        if not full_path.exists():
            return {'violations': [], 'warnings': [], 'tasks': [], 'error': 'File not found'}

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        doc_name = doc_path.split('\\')[0] if '\\' in doc_path else doc_path.split('/')[0]

        import os
        if not os.environ.get("MINIMAX_API_KEY"):
            return {
                'violations': [],
                'warnings': [],
                'tasks': [],
                'error': 'MINIMAX_API_KEY not configured'
            }

        print(f"    [LLM] Extracting tasks via Minimax API...")
        llm_tasks = llm_extract_tasks(doc_name, content)

        if not llm_tasks:
            return {
                'violations': [],
                'warnings': [],
                'tasks': [],
                'error': 'LLM extraction failed'
            }

        tasks = llm_tasks
        print(f"    [LLM] Extracted {len(tasks)} tasks")

        violations = []
        warnings = []

        for task in tasks:
            action = task.get('action', '')
            department = task.get('department')
            specific_role = task.get('specific_role')

            is_violation = False

            if not specific_role or specific_role == 'null':
                is_violation = True

            if specific_role and department and specific_role == department:
                is_violation = True

            if is_violation:
                flowchart_actors = self.find_flowchart_actors(doc_path, action, flowchart_mapping)

                if flowchart_actors:
                    warnings.append({
                        'action': action,
                        'department': department,
                        'specific_role': specific_role,
                        'flowchart_actors': flowchart_actors,
                        'note': f'Document does not specify position, but flowchart specifies {", ".join(flowchart_actors)}'
                    })
                else:
                    violations.append({
                        'action': action,
                        'department': department,
                        'specific_role': specific_role,
                        'issue': 'Neither document nor flowchart specifies specific position'
                    })

        return {
            'violations': violations,
            'warnings': warnings,
            'tasks': tasks,
            'error': None
        }

    def generate_report(self, results: List[Dict], output_file: Path):
        total_docs = len(results)
        docs_with_violations = sum(1 for r in results if r.get('violations'))
        docs_with_warnings = sum(1 for r in results if r.get('warnings'))
        total_violations = sum(len(r.get('violations', [])) for r in results)
        total_warnings = sum(len(r.get('warnings', [])) for r in results)

        report_lines = [
            "# Role Accountability Compliance Audit Report",
            "",
            f"**Audit Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Audit Scope**: L2 (Procedure) + L3 (Standard) Documents",
            "",
            "---",
            "",
            "## Audit Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Documents | {total_docs} |",
            f"| Documents with Violations | {docs_with_violations} |",
            f"| Documents with Warnings | {docs_with_warnings} |",
            f"| Total Violations | {total_violations} |",
            f"| Total Warnings | {total_warnings} |",
            "",
        ]

        if total_violations > 0:
            report_lines.extend([
                "## Severe Violations (Immediate Action Required)",
                "",
                "| Document | Action | Department | Issue |",
                "|----------|--------|-------------|-------|",
            ])

            for result in results:
                doc_path = result.get('doc_path', '')
                for violation in result.get('violations', []):
                    action = violation.get('action', '')[:40]
                    department = violation.get('department') or '-'
                    issue = violation.get('issue', '')
                    report_lines.append(f"| {doc_path} | {action} | {department} | {issue} |")

            report_lines.append("")

        if total_warnings > 0:
            report_lines.extend([
                "## Consistency Warnings (Verification Needed)",
                "",
                "| Document | Action | Doc Dept | Flowchart Roles | Note |",
                "|----------|--------|----------|------------------|------|",
            ])

            for result in results:
                doc_path = result.get('doc_path', '')
                for warning in result.get('warnings', []):
                    action = warning.get('action', '')[:30]
                    department = warning.get('department') or '-'
                    flowchart_actors = ', '.join(warning.get('flowchart_actors', []))
                    note = warning.get('note', '')
                    report_lines.append(f"| {doc_path} | {action} | {department} | {flowchart_actors} | {note} |")

            report_lines.append("")

        report_lines.extend([
            "## Extracted Task List (Full Reference)",
            "",
        ])

        for result in results:
            doc_path = result.get('doc_path', '')
            tasks = result.get('tasks', [])
            if tasks:
                report_lines.append(f"### {doc_path}")
                report_lines.append("")
                report_lines.append("| Action | Department | Specific Role |")
                report_lines.append("|--------|------------|---------------|")
                for task in tasks:
                    action = task.get('action', '')[:40]
                    department = task.get('department') or '-'
                    role = task.get('specific_role') or '-'
                    report_lines.append(f"| {action} | {department} | {role} |")
                report_lines.append("")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"Report generated: {output_file}")

    def run_audit(self, docs: List[str] = None, output_file: str = None) -> Dict[str, Any]:
        print("=" * 60)
        print("ComplianceAuditor - Role Accountability Audit")
        print("=" * 60)

        if docs is None:
            scope_file = self.dist_dir / 'actor_audit_scope.json'
            if scope_file.exists():
                with open(scope_file, 'r', encoding='utf-8') as f:
                    scope = json.load(f)
                docs = scope.get('l2', []) + scope.get('l3', [])
            else:
                docs = []
                if self.outputs_dir.exists():
                    for d in self.outputs_dir.iterdir():
                        if d.is_dir() and d.stem.startswith(('PROC', 'WORK')):
                            docs.append(d.stem)

        print(f"\n[1/3] Found {len(docs)} documents to audit")

        print("\n[2/3] Loading flowchart reference data...")
        flowchart_mapping = self.load_flowchart_data()

        print("\n[3/3] Analyzing documents for accountability issues...")

        results = []

        for i, doc_path in enumerate(docs, 1):
            print(f"  [{i}/{len(docs)}] Processing: {doc_path}")

            try:
                analysis = self.analyze_document(doc_path, flowchart_mapping)
                analysis['doc_path'] = doc_path
                results.append(analysis)

                violations = len(analysis.get('violations', []))
                warnings = len(analysis.get('warnings', []))
                if violations > 0 or warnings > 0:
                    print(f"    -> Violations: {violations}, Warnings: {warnings}")

            except Exception as e:
                print(f"    -> ERROR: {e}")
                results.append({
                    'doc_path': doc_path,
                    'violations': [],
                    'warnings': [],
                    'tasks': [],
                    'error': str(e)
                })

        if output_file is None:
            output_file = self.dist_dir / 'compliance_actor_audit.md'
        else:
            output_file = Path(output_file)

        self.generate_report(results, output_file)

        total_violations = sum(len(r.get('violations', [])) for r in results)
        total_warnings = sum(len(r.get('warnings', [])) for r in results)

        print("\n" + "=" * 60)
        print("AUDIT COMPLETE")
        print("=" * 60)
        print(f"Total documents: {len(results)}")
        print(f"Total violations: {total_violations}")
        print(f"Total warnings: {total_warnings}")
        print(f"Report: {output_file}")

        return {
            "total_documents": len(results),
            "total_violations": total_violations,
            "total_warnings": total_warnings,
            "report_path": str(output_file)
        }
