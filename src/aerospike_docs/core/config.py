# -*- coding: utf-8 -*-
"""Configuration for aerospike_docs library."""

import logging
import os
from dataclasses import dataclass, field
from typing import List


def _parse_bool_env(var_name: str, default: bool = False) -> bool:
    """Parse boolean environment variable safely."""
    value = os.getenv(var_name, "").lower().strip()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off", ""):
        return False
    logger = logging.getLogger(__name__)
    logger.warning(f"Invalid boolean value for {var_name}: '{value}', using default: {default}")
    return default


@dataclass
class ApiConfig:
    """API configuration for external services. Reads from os.environ only."""

    minimax_api_key: str = field(default_factory=lambda: os.getenv("MINIMAX_API_KEY", ""))
    minimax_api_url: str = field(
        default_factory=lambda: os.getenv(
            "MINIMAX_API_URL",
            "https://api.minimax.chat/v1/text/chatcompletion_v2"
        )
    )
    minimax_model_name: str = field(default_factory=lambda: os.getenv("MINIMAX_MODEL_NAME", ""))
    minimax_embedding_model: str = field(default_factory=lambda: os.getenv("MINIMAX_EMBEDDING_MODEL", ""))
    chroma_db_dir: str = field(default_factory=lambda: os.getenv("CHROMA_DB_DIR", "./data/chroma_db"))
    timeout: int = 30
    retry_times: int = 3
    max_tokens: int = 4000
    temperature: float = 0.7

    def __post_init__(self):
        if not self.minimax_model_name:
            logging.getLogger(__name__).warning(
                "MINIMAX_MODEL_NAME not configured. AI features will be disabled."
            )
        if not self.minimax_embedding_model:
            logging.getLogger(__name__).warning(
                "MINIMAX_EMBEDDING_MODEL not configured. RAG feature requires embedding model."
            )

    def is_configured(self) -> bool:
        return bool(self.minimax_api_key) and bool(self.minimax_model_name)


@dataclass
class ConversionConfig:
    """Document conversion settings."""
    encoding: str = "utf-8"
    timeout: int = 300
    image_types: List[str] = field(default_factory=lambda: ["流程图", "表格", "其他"])
    extract_images: bool = True
    preserve_formatting: bool = True


@dataclass
class DomainConfig:
    """Domain-specific configuration for terminology mining."""
    domain_context: str = """
本知识库属于【航空航天制造】领域，重点关注【复合材料零部件生产】。
涉及的核心业务包括：生产计划、数控加工、热压罐工艺、无损检测、质量管理体系 (AS9100)、适航法规 (CCAR-25)。
"""
    target_categories: List[str] = field(default_factory=lambda: [
        "专有缩写 (如 QRA, ACFT_B, BOM, MBD, NC, OTD)",
        "核心设备 (如 热压罐, 自动铺带机, 数控铣床, 激光跟踪仪)",
        "关键材料 (如 预浸料, 蜂窝芯, 碳纤维, 环氧树脂)",
        "工艺方法 (如 固化, 铺贴, 真空袋, 热压罐成型)",
        "质量术语 (如 不符合项, 偏离许可, 首件检验, 工序能力)",
        "工装模具 (如 成型工装, 定位工装, 装配型架)",
        "检测标准 (如 UT, RT, 目视检测, 超声检测)",
        "适航/规范 (如 CCAR-25, AS9100, 制造符合性)"
    ])
    negative_patterns: List[str] = field(default_factory=lambda: [
        "通知", "办法", "规定", "制度", "要求", "规范", "标准", "领导", "部门", "单位", "公司", "企业",
        "加强", "落实", "提高", "做好", "确保", "完成", "执行", "遵守", "按照", "根据", "通过", "进行",
        "立即", "马上", "及时", "尽快", "按时", "定期", "随时", "一般", "通常", "必要时",
        "相关", "有关", "各种", "一切", "所有", "其他", "其余", "原则上",
        "若干", "一些", "一定", "某些", "每个", "各项"
    ])
    domain_subtypes: List[str] = field(default_factory=lambda: [
        "工装/工装设备管理",
        "生产计划/排程",
        "数控加工/编程",
        "热压罐工艺",
        "复合材料铺贴",
        "无损检测 (NDT)",
        "质量管理体系",
        "适航/法规符合性",
        "供应链/库存管理",
        "安全管理/6S",
        "人力资源/培训",
        "其他（需从文本判断）"
    ])


# Module-level constant for 12-Factor pattern
_api_config = ApiConfig()
MINIMAX_MODEL_NAME = _api_config.minimax_model_name
