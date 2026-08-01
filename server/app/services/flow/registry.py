# -*- coding: utf-8 -*-
"""
Atom Registry：@register 装饰器 + load_all() 自动发现 atoms 包内全部模块。

自动发现避免每加一个原子就改 __init__（多并发开发时零冲突）。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from .base import Atom

_REGISTRY: dict[str, Type[Atom]] = {}
_loaded = False


def register(cls: Type[Atom]) -> Type[Atom]:
    """类装饰器：把 Atom 子类注册进目录。name 必须非空且唯一。"""
    if not cls.name:
        raise ValueError(f"{cls.__name__} 缺少 name")
    if cls.name in _REGISTRY:
        raise ValueError(f"原子名重复注册: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> Atom:
    """按名实例化原子（未找到抛 KeyError）。"""
    load_all()
    return _REGISTRY[name]()


def names() -> list[str]:
    load_all()
    return sorted(_REGISTRY)


def catalog() -> list[dict]:
    """原子目录（GET /api/atoms 用）：name/title/inputs/outputs/param_spec。"""
    load_all()
    return [
        {
            "name": cls.name,
            "title": cls.title,
            "inputs": cls.inputs,
            "outputs": cls.outputs,
            "param_spec": cls.param_spec,
        }
        for _, cls in sorted(_REGISTRY.items())
    ]


def load_all() -> None:
    """导入 flow.atoms 包内全部模块（幂等），触发各模块的 @register。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import atoms  # noqa: PLC0415

    for m in pkgutil.iter_modules(atoms.__path__):
        importlib.import_module(f"{__package__}.atoms.{m.name}")
