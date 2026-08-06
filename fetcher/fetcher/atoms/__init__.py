# -*- coding: utf-8 -*-
"""atoms：原子能力层（每个原子只做一件事并报告 Outcome）。"""

from fetcher.atoms.base import Atom
from fetcher.atoms.browser_ops import (
    CheckIPFresh,
    ColdStart,
    RelaunchBrowser,
    SaveCookies,
)
from fetcher.atoms.facebook import FetchFbPost
from fetcher.atoms.human import WaitHumanLogin, WaitHumanVerify
from fetcher.atoms.identity_ops import ClearIdentity
from fetcher.atoms.refresh import Refresh
from fetcher.atoms.sleep import BackoffSleep, Sleep, human_pause_duration
from fetcher.atoms.slider import SolveSlider, make_auto_solve, solve_all_sliders
from fetcher.atoms.wa_check import CheckWhatsApp

__all__ = [
    "Atom",
    "BackoffSleep",
    "CheckIPFresh",
    "CheckWhatsApp",
    "ClearIdentity",
    "ColdStart",
    "FetchFbPost",
    "Refresh",
    "RelaunchBrowser",
    "SaveCookies",
    "Sleep",
    "SolveSlider",
    "WaitHumanLogin",
    "WaitHumanVerify",
    "human_pause_duration",
    "make_auto_solve",
    "solve_all_sliders",
]
