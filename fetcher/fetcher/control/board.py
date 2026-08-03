# -*- coding: utf-8 -*-
"""状态板（迁移自 common.StatusBoard，行为不变）。

终端底部固定 workers 行显示各 worker 实时状态（不刷屏）。库与展示
解耦：CrawlLoop/Engine 只面向 set(wid, **fields) / log(msg) 两个方法
编程，board 作为可选 listener 注入；不传 board 时状态更新走 noop、
日志走 print。
"""

from __future__ import annotations

import sys
import threading
import time


def fmt_dur(sec: float) -> str:
    """秒 -> mm:ss（状态行倒计时用）。"""
    m, s = divmod(max(0, int(sec)), 60)
    return f"{m:02d}:{s:02d}"


def _disp_width(s: str) -> int:
    """字符串的终端显示宽度（CJK 全角字符占 2 列）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in s)


def _truncate_disp(s: str, max_cols: int) -> str:
    """按终端显示宽度截断（中文按 2 列算），防止超宽换行打乱固定行渲染。"""
    import unicodedata
    w, out = 0, []
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > max_cols:
            break
        out.append(ch)
        w += cw
    return "".join(out)


class StatusBoard:
    """终端底部固定 workers 行显示各 worker 实时状态（不刷屏）。

    - fields 结构由调用方自定，渲染格式由 compose(wid, fields) 回调决定；
      detail 字段保留给内部日志路由（set 时未显式给则清空）；
    - set() 更新某 worker 的状态字段并重绘整板（有最小重绘间隔节流）；
    - log() 把重要事件以滚动日志打印在状态板上方；
    - 非 TTY（重定向到文件/管道）时 set() 不重绘、log() 直接 print。
    """

    def __init__(self, n_workers: int, compose=None):
        self.n = n_workers
        self.tty = sys.stdout.isatty()
        self.lock = threading.Lock()
        self.compose = compose or (lambda wid, f: str(f.get("line", "")))
        self.fields = [{"detail": ""} for _ in range(n_workers)]
        self._started = False
        self._last_render = 0.0

    # ---- 渲染 ----

    def _width(self) -> int:
        import shutil
        return max(60, shutil.get_terminal_size((120, 24)).columns - 1)

    def _render_locked(self, force: bool = False):
        if not self.tty or not self._started:
            return
        now = time.monotonic()
        if not force and now - self._last_render < 0.2:
            return
        self._last_render = now
        out = [f"\033[{self.n}A"]  # 光标回到状态板首行
        for wid in range(self.n):
            f = self.fields[wid]
            line = self.compose(wid, f)
            if f.get("detail"):
                line += f" · {f['detail']}"
            out.append("\033[2K\r" + _truncate_disp(line, self._width()) + "\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # ---- 对外接口 ----

    def start(self):
        """预留状态板空间并首次绘制（启动日志打印完之后调用）。"""
        if self.tty and not self._started:
            sys.stdout.write("\n" * self.n)
            sys.stdout.flush()
            self._started = True
            with self.lock:
                self._render_locked(force=True)

    def set(self, wid: int, force: bool = False, **kw):
        """更新 worker 状态字段；未显式给 detail 时清空旧细节。"""
        with self.lock:
            f = self.fields[wid]
            if "detail" not in kw:
                f["detail"] = ""
            f.update(kw)
            self._render_locked(force=force)

    def log(self, msg: str):
        """重要事件：滚动打印在状态板上方（自动按显示宽度折行）。"""
        with self.lock:
            if not self.tty or not self._started:
                print(msg, flush=True)
                return
            width = self._width()
            lines = []
            for part in str(msg).splitlines() or [""]:
                while _disp_width(part) > width:
                    cut = _truncate_disp(part, width)
                    lines.append(cut)
                    part = part[len(cut):]
                lines.append(part)
            out = [f"\033[{self.n}A"]
            for ln in lines:
                out.append("\033[2K\r" + ln + "\n")
            for wid in range(self.n):
                f = self.fields[wid]
                line = self.compose(wid, f)
                if f.get("detail"):
                    line += f" · {f['detail']}"
                out.append("\033[2K\r"
                           + _truncate_disp(line, self._width()) + "\n")
            sys.stdout.write("".join(out))
            sys.stdout.flush()
            self._last_render = time.monotonic()


def wait_countdown(board: StatusBoard | None, wid: int, stop: threading.Event,
                   seconds: float, state_prefix: str,
                   set_status=None) -> bool:
    """可中断等待，状态行每秒刷新倒计时。返回 True 表示被用户中断。"""
    deadline = time.monotonic() + seconds
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        if set_status is not None:
            set_status(state=f"{state_prefix} 剩 {fmt_dur(remain)}")
        elif board is not None:
            board.set(wid, **{"state": f"{state_prefix} 剩 {fmt_dur(remain)}"})
        if stop.wait(min(1.0, remain)):
            return True
