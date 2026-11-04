# -*- coding: utf-8 -*-
"""GeoLab Agent —— 基于 EduWork / DSH 的地理科学虚拟实验智能体。

包结构：
    protocol   统一实验协议（参数声明、结构化校验、结果封装）
    registry   可插拔实验注册表
    service    四种执行模式（单次 / 扫描 / 对照 / 敏感性）
    experiments 具体实验内核
    agent      自然语言任务路由
    server     标准库 HTTP 服务
"""

__version__ = "1.0.0"
__all__ = ["protocol", "registry", "service", "server", "agent"]
