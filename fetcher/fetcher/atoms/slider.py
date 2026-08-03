# -*- coding: utf-8 -*-
"""SolveSlider 原子 + 真人轨迹回放引擎（迁移自 util/slider_track.py）。

思路（分工）：
    - CloakBrowser 负责"环境像人"（指纹 / CDP / TLS 源码级补丁）；
    - 本模块负责"动作像人"：轨迹库（包内资源 assets/tracks.json，
      由 util/slider_track.py record 录入的真人采样）随机抽一条，
      归一化后缩放到目标距离，按原始节奏喂给 page.mouse。

注意：回放直接调用原始 page.mouse API，绕过 humanize 的二次曲线化
（否则真人轨迹会被再叠加一层曲线化而变形）。

本模块只迁移「回放」能力；录入/CLI 测试工具仍留在 util/slider_track.py。
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult

# 多 worker 并发拖动互斥锁：多线程同时回放轨迹时 GIL 互相抢占，
# 鼠标事件成撮突发（卡一截跳一截），轨迹数据也会因突发被风控识破。
_DRAG_LOCK = threading.Lock()

# 轨迹库：包内资源（由 util/tracks.json 复制而来）
TRACKS_FILE = Path(__file__).resolve().parents[1] / "assets" / "tracks.json"

# 常见滑块把手选择器；阿里 nocaptcha 把手 id 前缀 nc_1_ 会变，后缀 _n1z 稳定
DEFAULT_HANDLE_SELECTORS = [
    "[id$='_n1z']",
    ".nc_iconfont.btn_slide",   # 阿里系滑块（类名兜底）
    ".slider-handle",
    ".verify-slider",
    ".slide-btn",
    "#drag-btn",
    ".geetest_slider_button",   # 极验
]


def measure_full_slide_distance(page, handle_selector: str = "[id$='_n1z']",
                                track_selector: str = "[id$='__scale_text']") -> float:
    """阿里 nocaptcha「拖到底」滑块的目标距离 = 轨道宽 - 把手宽。"""
    handle = page.locator(handle_selector).first
    track = page.locator(track_selector).first
    if not track.count():
        track = page.locator("[id$='__bg']").first
    hb, tb = handle.bounding_box(), track.bounding_box()
    if not hb or not tb:
        raise RuntimeError("无法测量轨道/把手尺寸，请检查选择器")
    return tb["width"] - hb["width"]


# ---------------------------------------------------------------- 轨迹库

def load_tracks(path: Path = TRACKS_FILE) -> list:
    if not Path(path).exists():
        raise FileNotFoundError(f"轨迹库不存在：{path}，先用 util/slider_track.py record 录入")
    tracks = [json.loads(line)
              for line in Path(path).read_text(encoding="utf-8").splitlines()
              if line.strip()]
    return [t for t in tracks if len(t) >= 10]


def _densify(points, step_ms=10):
    """把稀疏轨迹按固定时间步长线性插值加密（解决回放卡顿）。"""
    if len(points) < 2:
        return points
    total_ms = points[-1][2]
    dense, j, t = [], 0, 0.0
    while t <= total_ms:
        while j < len(points) - 2 and points[j + 1][2] < t:
            j += 1
        x0, y0, t0 = points[j]
        x1, y1, t1 = points[j + 1]
        r = 0.0 if t1 == t0 else max(0.0, min(1.0, (t - t0) / (t1 - t0)))
        dense.append((x0 + (x1 - x0) * r, y0 + (y1 - y0) * r, t))
        t += step_ms
    dense.append(points[-1])
    return dense


def _raw_mouse(page):
    """取原始（未拟人化）的鼠标方法，绕过 humanize 的二次曲线化。"""
    orig = getattr(page, "_original", None)
    if orig is not None:
        try:
            return orig.mouse_move, orig.mouse_down, orig.mouse_up
        except AttributeError:
            pass
    return page.mouse.move, page.mouse.down, page.mouse.up


def replay_track(page, handle_selector: str, distance: float,
                 track: list = None, y_dampen: float = 0.7,
                 tracks_path: Path = TRACKS_FILE):
    """随机（或指定）抽一条真人轨迹，缩放到 distance 后在把手元素上回放。"""
    track = track or random.choice(load_tracks(tracks_path))

    box = page.locator(handle_selector).first.bounding_box()
    if not box:
        raise RuntimeError(f"找不到把手元素：{handle_selector}")
    sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    # 归一化：起点归零，X 线性缩放到目标距离，Y 保留抖动形态（不缩放只降幅），
    # 时间轴按原始节奏保留——真人的加减速是最难伪造的特征
    x0, y0, t0 = track[0]
    x_span = track[-1][0] - x0
    if abs(x_span) < 1:
        raise RuntimeError("所选轨迹水平位移过小，请换一条")
    scale = distance / x_span
    points = [((x - x0) * scale, (y - y0) * y_dampen, t - t0)
              for x, y, t in track]
    dense = _densify(points)

    move, mdown, mup = _raw_mouse(page)
    with _DRAG_LOCK:
        move(sx + random.uniform(-2, 2), sy + random.uniform(-2, 2))
        time.sleep(random.uniform(0.2, 0.45))
        mdown()
        time.sleep(random.uniform(0.05, 0.15))
        # 绝对时钟对表发送：睡过了就直接发，误差不累积（防卡顿的关键）
        start = time.monotonic()
        for dx, dy, t_ms in dense:
            target = start + t_ms / 1000.0
            now = time.monotonic()
            if target > now:
                time.sleep(target - now)
            move(sx + dx, sy + dy)
        time.sleep(random.uniform(0.05, 0.15))
        mup()


# ---------------------------------------------------------------- 滑块检测（回放引擎内部用）

def _find_slider(page, selectors=("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")):
    """在所有 frame 里找可见的滑块把手，返回 (frame, selector, box) 或 None。"""
    for fr in page.frames:
        for sel in selectors:
            try:
                loc = fr.locator(sel).first
                if loc.count() and loc.is_visible():
                    return fr, sel, loc.bounding_box()
            except Exception:  # noqa: BLE001
                pass
    return None


def _measure_distance(fr, handle_box) -> float:
    """量目标距离 = 轨道宽 - 把手宽；量不到给默认 258。"""
    for tsel in ("[id$='__scale_text']", "[id$='__bg']", ".nc_scale_text"):
        try:
            tb = fr.locator(tsel).first.bounding_box()
            if tb:
                return tb["width"] - handle_box["width"]
        except Exception:  # noqa: BLE001
            pass
    return 258.0


_SLIDER_KEYWORD_JS = """() => {
    // 深度扫描文本（穿透 open shadowRoot），找滑块验证关键词
    const kw = /请按住滑块|按住滑块|滑动.{0,8}(验证|检测|校验)|拖动.{0,8}(滑块|验证|检测|到最右)|slide to (verify|unlock)/i;
    const parts = [];
    const walk = (node, depth) => {
        if (depth > 60 || parts.length > 4000) return;
        if (node.nodeType === Node.TEXT_NODE) { parts.push(node.textContent); return; }
        if (node.shadowRoot) walk(node.shadowRoot, depth + 1);
        const kids = node.children || node.childNodes || [];
        for (const c of kids) walk(c, depth + 1);
    };
    try { walk(document.body || document.documentElement, 0); } catch (e) {}
    const m = parts.join(' ').match(kw);
    return m ? m[0] : '';
}"""


def _slider_keyword_hit(page) -> str:
    """在所有 frame 里深度扫描滑块关键词，命中返回关键词文本。"""
    for fr in page.frames:
        try:
            hit = fr.evaluate(_SLIDER_KEYWORD_JS)
            if hit:
                return f"[{fr.url[:40]}] {hit}"
        except Exception:  # noqa: BLE001
            pass
    return ""


def _slider_present(page, sels) -> bool:
    """滑块是否还在：把手元素可见，或页面上有滑块验证关键词。"""
    if _find_slider(page, sels):
        return True
    hit = _slider_keyword_hit(page)
    if hit:
        print(f"[solve] 检测到滑块关键词: {hit}")
        return True
    return False


# ---------------------------------------------------------------- 多层滑块求解

def solve_all_sliders(page, selectors: list = None, max_rounds: int = 3,
                      max_attempts: int = 8,
                      tracks_path: Path = TRACKS_FILE) -> bool:
    """多层滑块循环：阿里风控常"过一关弹一关"。

    每过完一关重新全页扫描（所有 frame + shadow DOM，按把手元素 +
    关键词双重检测），发现还有滑块就继续打，直到页面上彻底没有滑块
    信号。返回 True = 页面上已无滑块；False = 打不动或层数超限。
    """
    for rnd in range(1, max_rounds + 1):
        sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
        if not _slider_present(page, sels):
            print(f"[solve] ✓ 页面已无滑块信号（第 {rnd - 1} 关后确认）" if rnd > 1
                  else "[solve] 页面上没有滑块")
            return True
        if rnd > 1:
            print(f"[solve] 检测到第 {rnd} 层滑块（模态框/嵌套组件），继续处理……")
            page.wait_for_timeout(1200)
        ok = solve_with_retry(page, selectors=list(sels), max_attempts=max_attempts,
                              tracks_path=tracks_path)
        if not ok:
            print(f"[solve] ✗ 第 {rnd} 层滑块 {max_attempts} 次尝试均未通过")
            return False
        page.wait_for_timeout(1500)
    sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    remaining = _slider_present(page, sels)
    if remaining:
        print(f"[solve] ✗ 已达最大层数 {max_rounds}，页面上仍有滑块")
    return not remaining


def _judge_result(page, sels, timeout_s: float = 5.0, success_selector: str = None) -> bool:
    """严格判定验证结果（修复"失败被误判成功"）。"""
    deadline = time.time() + timeout_s
    gone_streak = 0
    while time.time() < deadline:
        try:
            err = page.evaluate("""() => {
                const el = document.querySelector('#nocaptcha, .nc-container, [id^="nc_"]');
                if (!el) return '';
                const t = (el.innerText || '') + ' ' + (el.textContent || '');
                return /太快|失败|错误|再试|频繁|error|fail/i.test(t) ? t.slice(0, 80) : '';
            }""")
        except Exception:  # noqa: BLE001
            err = ""
        if err:
            print(f"[judge] 检测到滑块报错文案: {err.strip()[:40]}")
            return False
        if success_selector:
            try:
                if page.locator(success_selector).first.count():
                    return True
            except Exception:  # noqa: BLE001
                pass
        if _find_slider(page, sels):
            gone_streak = 0
        else:
            gone_streak += 1
            if gone_streak >= 4:
                return True
        page.wait_for_timeout(350)
    return False


def _click_retry_if_needed(page, sels, timeout_s: float = 6.0) -> bool:
    """失败后阿里滑块常进入"验证失败，点击框体重试"状态，需先点击
    错误框重新渲染滑块。返回 True = 当前已是可拖动状态。"""
    if _find_slider(page, sels):
        return True

    err_box = None
    for fr in page.frames:
        for sel in (".errloading", "[class*='errloading']", "[id*='nc_'][class*='err']"):
            try:
                loc = fr.locator(sel).first
                if loc.count() and loc.is_visible():
                    err_box = loc.bounding_box()
                    break
            except Exception:  # noqa: BLE001
                pass
        if err_box:
            break
    if not err_box:
        for fr in page.frames:
            try:
                loc = fr.locator("text=/点击.*重试|点击框体/").first
                if loc.count() and loc.is_visible():
                    err_box = loc.bounding_box()
                    break
            except Exception:  # noqa: BLE001
                pass

    if not err_box:
        return False

    cx = err_box["x"] + err_box["width"] / 2 + random.uniform(-3, 3)
    cy = err_box["y"] + err_box["height"] / 2 + random.uniform(-2, 2)
    page.mouse.move(cx, cy)
    time.sleep(random.uniform(0.15, 0.35))
    page.mouse.down()
    time.sleep(random.uniform(0.05, 0.12))
    page.mouse.up()
    print("[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _find_slider(page, sels):
            print("[solve] 滑块已重新渲染")
            return True
        page.wait_for_timeout(400)
    print("[solve] 点击后滑块未重渲")
    return False


def solve_with_retry(page, selectors: list = None, success_selector: str = None,
                     max_attempts: int = 8,
                     tracks_path: Path = TRACKS_FILE) -> bool:
    """滑块兜底（多轮重试 + 多轮刷新 + 轨迹轮换）。"""
    sels = selectors or ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    tracks = load_tracks(tracks_path)
    pool = tracks[:]
    random.shuffle(pool)

    def _next_track():
        nonlocal pool
        if not pool:
            pool = tracks[:]
            random.shuffle(pool)
        return pool.pop()

    for attempt in range(1, max_attempts + 1):
        # 连续失败 2 次 → 刷新页面重新等滑块（第 3、5、7… 次尝试前）
        if attempt > 2 and (attempt - 1) % 2 == 0:
            print(f"[solve] 已连续失败 {attempt - 1} 次，刷新页面重新等滑块……")
            try:
                page.reload(timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            deadline = time.time() + 10
            while time.time() < deadline and not _find_slider(page, sels):
                page.wait_for_timeout(500)
        if not _click_retry_if_needed(page, sels):
            found = _find_slider(page, sels)
            if not found:
                if not _slider_present(page, sels):
                    return True
                continue
        found = _find_slider(page, sels)
        if not found:
            if not _slider_present(page, sels):
                return True
            continue
        fr, sel, box = found
        distance = _measure_distance(fr, box)
        track = _next_track()
        print(f"[solve] 第 {attempt}/{max_attempts} 次尝试：回放 {len(track)} 点轨迹，"
              f"距离 {distance:.0f}px（剩余未用轨迹 {len(pool)} 条）")
        try:
            replay_track(page, sel, distance, track=track)
        except Exception as e:  # noqa: BLE001
            print(f"[solve] 回放异常: {type(e).__name__}: {e}")
        if _judge_result(page, sels, success_selector=success_selector):
            print(f"[solve] ✓ 第 {attempt} 次尝试通过")
            return True
        print(f"[solve] 第 {attempt} 次失败")
        page.wait_for_timeout(1500)
    return False


def try_solve_slider(page, selectors: list = None,
                     max_attempts: int = 8,
                     tracks_path: Path = TRACKS_FILE) -> bool:
    """检测页面上是否存在滑块，发现即用真人轨迹回放拖动。"""
    sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    if not _slider_present(page, sels):
        return False   # 页面上没有滑块
    return solve_all_sliders(page, selectors=selectors, max_attempts=max_attempts,
                             tracks_path=tracks_path)


# ---------------------------------------------------------------- 原子

class SolveSlider:
    """过滑块验证原子：params = {"max_attempts": 8, "max_rounds": 3}。

    返回 OK = 页面上已无滑块信号；BLOCKED = 打不动；
    SKIPPED = 配置关闭了自动过证；FATAL/NET_ERROR = 执行中浏览器/网络异常。
    """

    name = "solve_slider"
    title = "过滑块验证"

    def run(self, ctx, params: dict) -> ActionResult:
        if not ctx.config.auto_solve_slider:
            return ActionResult.skipped("配置关闭了自动过证")
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")
        try:
            ok = solve_all_sliders(
                page,
                max_rounds=int(params.get("max_rounds", 3)),
                max_attempts=int(params.get("max_attempts", 8)))
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(f"过证时浏览器死亡: {reason}")
            if kind == "net_error":
                return ActionResult.net_error(f"过证时网络层错误: {reason}")
            return ActionResult.blocked(f"过证异常: {reason}")
        if ok:
            return ActionResult.success("滑块已全部通过")
        return ActionResult.blocked("滑块未通过（轨迹库或环境分问题）")


def make_auto_solve(max_attempts: int = 8, max_rounds: int = 3):
    """生成 BrowserManager(warmup) / WaitHuman 用的 auto_solve 回调。"""

    def _solve(page) -> bool:
        return solve_all_sliders(page, max_rounds=max_rounds,
                                 max_attempts=max_attempts)

    return _solve
