# -*- coding: utf-8 -*-
"""
原子能力 + DAG 流水线（docs/flow-architecture.md）。

- base.py     Atom / AtomResult / Context 契约
- registry.py Atom Registry（@register 装饰器 + load_all 自动发现）
- atoms/      原子实现（P0 从现有 workers 抽取，行为不变）
"""
