#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真人轨迹 录入 / 回放 工具 —— 配合 CloakBrowser 模拟人工拖动滑块

思路（分工）：
    - CloakBrowser 负责"环境像人"（指纹 / CDP / TLS 源码级补丁）；
    - 本脚本负责"动作像人"：在真实浏览器里录下你手工拖动的轨迹（含时间戳），
      存成 JSON 轨迹库；回放时随机抽一条，归一化后缩放到目标距离，
      按原始节奏喂给 page.mouse，从按下到抬起完整复现真人手感。

为什么不直接用 humanize=True 拖动：
    humanize 的贝塞尔曲线是程序生成的，轨迹库用的是真人采样——
    采样率、抖动形态、加减速节奏都更真实，更难被服务端轨迹建模识破。
    注意：回放时本脚本直接调用原始 page.mouse API，不经过 humanize 二次加工
    （否则真人轨迹会被再叠加一层曲线化而变形）。

轨迹库格式（tracks.json，每行一条 JSON 数组）：
    [[x, y, t_ms], ...]   —— mousedown 到 mouseup 之间的全部 mousemove 采样点

用法：
    # 1) 录入轨迹（headed 模式，在打开的浏览器里手工拖滑块，每次拖完回车保存）
    python util/slider_track.py record --url https://example.com

    # 2) 在代码里回放（滑块检测 + 触发）
    from util.slider_track import try_solve_slider
    solved = try_solve_slider(page, distance=260)

    # 3) 命令行测试回放效果
    python util/slider_track.py replay --url https://example.com \
        --selector .slider-handle --distance 260

必要依赖:
    pip install cloakbrowser
"""

import argparse
import atexit
import json
import random
import signal
import sys
import threading
import time

# 多 worker 并发拖动互斥锁：4 个线程同时回放轨迹时 GIL 互相抢占，
# 鼠标事件成撮突发（卡一截跳一截），轨迹数据也会因突发被风控识破。
# 同一时间只允许一个线程执行拖动，一次拖动约 1~2s，竞争开销可忽略。
_DRAG_LOCK = threading.Lock()
from pathlib import Path

# 轨迹库默认放在本脚本旁边，可后续按需挪到 .cache/
TRACKS_FILE = Path(__file__).resolve().parent / "tracks.json"


def _launch_guarded(**kw):
    """
    启动 CloakBrowser 并保证任何退出路径（异常 / Ctrl-C / SIGTERM / 超时强杀）
    都会调用 browser.close() 释放云端会话席位——此前崩溃路径跳过 close()，
    租约挂在服务端不释放，多次叠加就把席位占满了。
    """
    from cloakbrowser import launch

    browser = launch(**kw)
    _state = {"closed": False}

    def _close(*_args):
        if not _state["closed"]:
            _state["closed"] = True
            try:
                browser.close()
            except Exception:
                pass

    atexit.register(_close)
    def _on_signal(signum, frame):
        _close()
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    return browser

# 常见滑块把手选择器，按目标站点补充；try_solve_slider 依次探测
DEFAULT_HANDLE_SELECTORS = [
    "[id$='_n1z']",             # 阿里 nocaptcha 滑块把手（1688/淘宝，id 前缀 nc_1_ 会变，后缀 _n1z 稳定）
    ".nc_iconfont.btn_slide",   # 阿里系滑块（类名兜底）
    ".slider-handle",
    ".verify-slider",
    ".slide-btn",
    "#drag-btn",
    ".geetest_slider_button",   # 极验
]


def measure_full_slide_distance(page, handle_selector: str = "[id$='_n1z']",
                                track_selector: str = "[id$='__scale_text']") -> float:
    """
    阿里 nocaptcha「拖到底」滑块的目标距离 = 轨道宽 - 把手宽。
    轨道元素按页面实际结构调整，常见的有 [id$='__scale_text'] / [id$='__bg'] / .nc_scale_text。
    """
    handle = page.locator(handle_selector).first
    track = page.locator(track_selector).first
    if not track.count():
        track = page.locator("[id$='__bg']").first
    hb, tb = handle.bounding_box(), track.bounding_box()
    if not hb or not tb:
        raise RuntimeError("无法测量轨道/把手尺寸，请检查选择器")
    return tb["width"] - hb["width"]


# ---------------------------------------------------------------- 录制

_RECORD_JS = """
window.__track = [];
window.__recording = false;
// 捕获阶段（true）：先于页面 JS 的 stopPropagation 触发，确保一定能收到
['mousedown', 'pointerdown'].forEach(ev =>
    document.addEventListener(ev, () => {
        window.__recording = true;
        window.__track = [];
    }, true));
['mousemove', 'pointermove'].forEach(ev =>
    document.addEventListener(ev, e => {
        // 只采 mousemove，pointermove 跳过避免重复点
        if (window.__recording && ev === 'mousemove')
            window.__track.push([e.clientX, e.clientY, performance.now()]);
    }, true));
['mouseup', 'pointerup'].forEach(ev =>
    document.addEventListener(ev, () => { window.__recording = false; }, true));
window.__track_probe = () => window.__track.length;
"""


def _collect_track(page) -> list:
    """
    从所有 frame 里取采样点最多的那条轨迹（滑块常在 iframe 里，
    iframe 内的鼠标事件不会冒泡到主文档）。
    iframe 内坐标会换算成主页面坐标，回放时无需区分 frame。
    """
    best = []
    for frame in page.frames:
        try:
            t = frame.evaluate("window.__track || []")
        except Exception:
            continue
        if not t or len(t) <= len(best):
            continue
        if frame.parent_frame:  # 子 frame：坐标相对 iframe 视口，换算到主页面
            try:
                fb = frame.frame_element().bounding_box()
                if fb:
                    t = [[x + fb["x"], y + fb["y"], ts] for x, y, ts in t]
            except Exception:
                pass
        best = t
    return best


def record_tracks(url: str, max_tracks: int = 20):
    """headed 打开目标页面，循环录制手工拖动轨迹，追加写入 tracks.json。"""
    browser = _launch_guarded(headless=False)
    page = browser.new_page()
    # 用 add_init_script 注入：页面跳转/刷新后监听自动重注，且每个 frame 都会注入
    # （1688 验证通过后会跳转到真实页面，回来录下一条时监听不会丢）
    page.add_init_script(_RECORD_JS)
    page.goto(url)

    print(f"[record] 已打开 {url}")
    print(f"[record] 每拖完一次滑块后回终端按回车保存；直接回车跳过；输入 q 退出")
    print(f"[record] 验证通过跳走后，在浏览器地址栏重新打开验证页 URL 即可继续录")
    print(f"[record] 目标：录 {max_tracks} 条左右，轨迹库越大越好")

    saved = 0
    with open(TRACKS_FILE, "a", encoding="utf-8") as f:
        while saved < max_tracks:
            cmd = input(f"[record] 第 {saved + 1} 条：拖完按回车保存 / 回车重采 / q 退出 > ").strip()
            if cmd.lower() == "q":
                break
            track = _collect_track(page)
            if not track or len(track) < 10:
                print(f"[record] 采样点太少（{len(track) if track else 0} 个），没录到，请重新拖一次")
                # 诊断：打印每个 frame 的注入状态和采样数，判断监听是否生效
                for fr in page.frames:
                    try:
                        n = fr.evaluate("window.__track ? window.__track.length : -1")
                        print(f"[record]   frame [{fr.url[:60]}] 采样数={n}"
                              f"（-1 表示监听未注入）")
                    except Exception as e:
                        print(f"[record]   frame [{fr.url[:60]}] 读取失败: {e}")
                continue
            f.write(json.dumps(track) + "\n")
            f.flush()
            saved += 1
            duration = (track[-1][2] - track[0][2]) / 1000
            distance = track[-1][0] - track[0][0]
            print(f"[record] ✓ 已保存：{len(track)} 点，水平 {distance:.0f}px，耗时 {duration:.2f}s")

    browser.close()
    print(f"[record] 完成，共保存 {saved} 条 → {TRACKS_FILE}")


def _find_slider(page, selectors: tuple = ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")):
    """在所有 frame 里找可见的滑块把手，返回 (frame, selector, box) 或 None。"""
    for fr in page.frames:
        for sel in selectors:
            try:
                loc = fr.locator(sel).first
                if loc.count() and loc.is_visible():
                    return fr, sel, loc.bounding_box()
            except Exception:
                pass
    return None


def record_tracks_auto(url: str, max_tracks: int = 5, timeout_s: int = 240):
    """
    无人值守录制：循环访问直到滑块出现 → 轮询所有 frame，
    检测到一次完成的拖动（采样点停止增长或页面跳走）就自动保存。
    """
    browser = _launch_guarded(headless=False)
    page = browser.new_page()
    page.add_init_script(_RECORD_JS)

    deadline = time.time() + timeout_s
    saved = 0

    # --- 阶段 1：等滑块出现（不常弹，反复刷新碰风控） ---
    print(f"[auto] 打开 {url}，等待滑块出现……")
    found = None
    while time.time() < deadline and not found:
        try:
            page.goto(url, timeout=20000)
        except Exception as e:
            if "TargetClosed" in type(e).__name__:
                print("[auto] 浏览器会话被服务端终止（席位/租约问题），不再重试，直接退出")
                return
            print(f"[auto] goto 异常（忽略）: {type(e).__name__}")
        page.wait_for_timeout(2500)
        found = _find_slider(page)
        if not found:
            print(f"[auto] 本次未出现滑块（可能是真实页直接放行），3s 后刷新重试……")
            page.wait_for_timeout(3000)
    if not found:
        print("[auto] 超时：一直没等到滑块。")
        browser.close()
        return

    fr, sel, box = found
    print(f"[auto] ★ 滑块出现！把手 {sel} @ {fr.url[:50]}，box={box}")
    print(f"[auto] 请在浏览器里拖动滑块（自然速度，可快可慢可停顿），我会自动保存轨迹")

    # --- 阶段 2：轮询采集，拖完一条自动存一条 ---
    pending, last_grow, last_sig = [], 0.0, None
    with open(TRACKS_FILE, "a", encoding="utf-8") as f:
        while saved < max_tracks and time.time() < deadline:
            track = _collect_track(page)
            now = time.time()
            if len(track) > len(pending):
                pending, last_grow = track, now
            # 停止增长 0.8s，或页面跳走（track 变空但手里有货）→ 落盘
            done = pending and (now - last_grow > 0.8 or (not track and len(pending) >= 10))
            if done and len(pending) >= 10:
                sig = (len(pending), round(pending[-1][2]))
                if sig != last_sig:
                    f.write(json.dumps(pending) + "\n"); f.flush()
                    saved += 1; last_sig = sig
                    dur = (pending[-1][2] - pending[0][2]) / 1000
                    dist = pending[-1][0] - pending[0][0]
                    print(f"[auto] ✓ 已保存第 {saved} 条：{len(pending)} 点，"
                          f"水平 {dist:.0f}px，耗时 {dur:.2f}s")
                    if saved >= max_tracks:
                        break
                    print(f"[auto] 已存 {saved}/{max_tracks} 条；滑块若跳走，"
                          f"请在地址栏重新打开验证页继续拖")
                pending = []
            elif done:
                pending = []
            page.wait_for_timeout(250)

    browser.close()
    print(f"[auto] 结束，本轮共保存 {saved} 条 → {TRACKS_FILE}")


# ---------------------------------------------------------------- 回放

def replay_auto(url: str, timeout_s: int = 180):
    """
    全自动回放测试：循环访问直到滑块出现 → 自动量距离 → 用轨迹库回放 → 判定结果。
    """
    browser = _launch_guarded(headless=False)
    page = browser.new_page()
    deadline = time.time() + timeout_s

    print(f"[replay] 打开 {url}，等待滑块出现……")
    found = None
    while time.time() < deadline and not found:
        try:
            page.goto(url, timeout=20000)
        except Exception as e:
            if "TargetClosed" in type(e).__name__:
                print("[replay] 浏览器会话被服务端终止（席位/租约问题），不再重试，直接退出")
                return
            print(f"[replay] goto 异常（忽略）: {type(e).__name__}")
        page.wait_for_timeout(2500)
        found = _find_slider(page)
        if not found:
            print(f"[replay] 未出现滑块（直接放行），3s 后刷新重试……")
            page.wait_for_timeout(3000)
    if not found:
        print("[replay] 超时：一直没等到滑块（侧面说明 CloakBrowser 穿透率不错）")
        browser.close()
        return

    # 多层滑块循环：每层内部量距 + 回放 + 失败重试；
    # 过完一关全页扫描（含模态框/嵌套组件），还有滑块就继续打
    ok = solve_all_sliders(page)

    if not ok:
        print("[replay] ✗ 滑块未全部通过（轨迹库或环境分问题）")
        page.screenshot(path="util/_replay_fail.png")
        print("[replay] 截图已存 util/_replay_fail.png")
    else:
        print(f"[replay] ✓ 验证通过！当前页面: {page.url[:80]}")
        page.screenshot(path="util/_replay_ok.png")
        print("[replay] 截图已存 util/_replay_ok.png")
    page.wait_for_timeout(2000)
    browser.close()


def load_tracks(path: Path = TRACKS_FILE) -> list:
    if not path.exists():
        raise FileNotFoundError(f"轨迹库不存在：{path}，先运行 record 子命令录入")
    tracks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [t for t in tracks if len(t) >= 10]


def _densify(points, step_ms=10):
    """
    把稀疏轨迹按固定时间步长线性插值加密（解决回放卡顿）。
    原始轨迹 30~50 个点、间隔不均，逐点 sleep 会累积误差导致抖动；
    加密到 10ms 一个点后配合绝对时钟发送，运动就平滑了。
    points: [(x, y, t_ms), ...]
    """
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
    """
    取原始（未拟人化）的鼠标方法。
    humanize=True 会把 page.mouse.move 替换为贝塞尔曲线版本——高层操作
    （click/type）用它很好，但轨迹回放必须绕过：否则我们加密后的每个点
    都被再做一次多步曲线化，0.8s 的轨迹被拖成 4s 蠕行（已实测复现）。
    cloakbrowser 把原始方法保存在 page._original.{mouse_move,mouse_down,mouse_up}。
    """
    orig = getattr(page, "_original", None)
    if orig is not None:
        try:
            return orig.mouse_move, orig.mouse_down, orig.mouse_up
        except AttributeError:
            pass
    return page.mouse.move, page.mouse.down, page.mouse.up


def replay_track(page, handle_selector: str, distance: float,
                 track: list = None, y_dampen: float = 0.7):
    """
    随机（或指定）抽一条真人轨迹，缩放到 distance 后在把手元素上回放。

    参数:
        handle_selector: 滑块把手的 CSS 选择器
        distance:        需要拖动的水平距离 px（缺口滑块一般由图像识别算出）
        track:           可选，指定轨迹；None 则从轨迹库随机抽一条
        y_dampen:        垂直抖动降幅（保留形态、缩小幅度，0~1）
    """
    track = track or random.choice(load_tracks())

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
    dense = _densify(points)   # 插值加密到 10ms 一点

    # 对准把手（带随机偏移）→ 停顿 → 按住 → 按原始节奏回放 → 稍停 → 松手
    # 整段在 _DRAG_LOCK 内执行：多 worker 并发时串行拖动，避免线程间
    # 互相抢占导致鼠标事件突发（卡顿/跳段），每次仅占用 1~2s
    # 必须用原始鼠标方法（_raw_mouse）：绕过 humanize 的二次曲线化
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


def _measure_distance(fr, handle_box) -> float:
    """量目标距离 = 轨道宽 - 把手宽；量不到给默认 258。"""
    for tsel in ("[id$='__scale_text']", "[id$='__bg']", ".nc_scale_text"):
        try:
            tb = fr.locator(tsel).first.bounding_box()
            if tb:
                return tb["width"] - handle_box["width"]
        except Exception:
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
    """在所有 frame 里深度扫描滑块关键词（模态框/不同组件都算），命中返回关键词文本。"""
    for fr in page.frames:
        try:
            hit = fr.evaluate(_SLIDER_KEYWORD_JS)
            if hit:
                return f"[{fr.url[:40]}] {hit}"
        except Exception:
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


def solve_all_sliders(page, selectors: list = None, max_rounds: int = 3) -> bool:
    """
    多层滑块循环：阿里风控常"过一关弹一关"（底层验证页过了，上层模态框又弹一块滑块）。
    每过完一关重新全页扫描（所有 frame + shadow DOM，按把手元素 + 关键词双重检测），
    发现还有滑块就继续打，直到页面上彻底没有滑块信号。
    返回 True = 页面上已无滑块（全部通过）；False = 打不动或层数超限。
    """
    for rnd in range(1, max_rounds + 1):
        sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
        if not _slider_present(page, sels):
            print(f"[solve] ✓ 页面已无滑块信号（第 {rnd - 1} 关后确认）" if rnd > 1
                  else "[solve] 页面上没有滑块")
            return True
        if rnd > 1:
            print(f"[solve] 检测到第 {rnd} 层滑块（模态框/嵌套组件），继续处理……")
            # 第二层滑块可能在弹层渲染中，给它一点稳定时间
            page.wait_for_timeout(1200)
        # 单层解决：注意这里不能再传 success_selector（真实页可能已在底层显示，
        # 但上层还有滑块），每关的通过只看该滑块组件自身的消失/报错
        ok = solve_with_retry(page, selectors=list(sels))
        if not ok:
            print(f"[solve] ✗ 第 {rnd} 层滑块三次尝试均未通过")
            return False
        page.wait_for_timeout(1500)   # 等下一层弹层出现（如果有）
    # 循环结束后最后确认一次
    sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    remaining = _slider_present(page, sels)
    if remaining:
        print(f"[solve] ✗ 已达最大层数 {max_rounds}，页面上仍有滑块")
    return not remaining


def _judge_result(page, sels, timeout_s: float = 5.0, success_selector: str = None) -> bool:
    """
    严格判定验证结果（修复"失败被误判成功"）：
      - 滑块区域出现报错文案（操作太快/失败/再试等）→ 立即判失败；
      - 给出 success_selector（如 1688 真实页的 buyer-workbench）且其出现 → 判成功；
      - 滑块把手连续消失 ≥1.2s（排除失败报错时的短暂隐藏空窗）→ 判成功；
      - 超时仍不确定 → 判失败。
    """
    deadline = time.time() + timeout_s
    gone_streak = 0
    while time.time() < deadline:
        # 1) 显式失败信号：nocaptcha 容器内的报错文案
        try:
            err = page.evaluate("""() => {
                const el = document.querySelector('#nocaptcha, .nc-container, [id^="nc_"]');
                if (!el) return '';
                const t = (el.innerText || '') + ' ' + (el.textContent || '');
                return /太快|失败|错误|再试|频繁|error|fail/i.test(t) ? t.slice(0, 80) : '';
            }""")
        except Exception:
            err = ""
        if err:
            print(f"[judge] 检测到滑块报错文案: {err.strip()[:40]}")
            return False
        # 2) 显式成功信号：真实页标志出现
        if success_selector:
            try:
                if page.locator(success_selector).first.count():
                    return True
            except Exception:
                pass
        # 3) 滑块连续消失才算数（每轮 350ms，连续 4 轮 ≈ 1.4s）
        if _find_slider(page, sels):
            gone_streak = 0
        else:
            gone_streak += 1
            if gone_streak >= 4:
                return True
        page.wait_for_timeout(350)
    return False


def _click_retry_if_needed(page, sels, timeout_s: float = 6.0) -> bool:
    """
    状态判断：失败后阿里滑块常进入"验证失败，点击框体重试"状态（滑块消失，
    必须先点击错误框重新渲染滑块，才能再拖）。
    返回 True = 当前已是可拖动状态（本来就有滑块，或点击后滑块已重渲）。
    """
    if _find_slider(page, sels):
        return True   # 已有滑块可拖，无需点击

    # 找"点击框体重试"错误框（阿里结构：.errloading / 含"重试"文案的可点击区域）
    err_box = None
    for fr in page.frames:
        for sel in (".errloading", "[class*='errloading']", "[id*='nc_'][class*='err']"):
            try:
                loc = fr.locator(sel).first
                if loc.count() and loc.is_visible():
                    err_box = loc.bounding_box()
                    break
            except Exception:
                pass
        if err_box:
            break
    if not err_box:
        # 兜底：按文案找（"点击…重试"）
        for fr in page.frames:
            try:
                loc = fr.locator("text=/点击.*重试|点击框体/").first
                if loc.count() and loc.is_visible():
                    err_box = loc.bounding_box()
                    break
            except Exception:
                pass

    if not err_box:
        return False   # 既不是滑块也没有重试框：可能已通过/已消失

    # 拟人点击错误框中心
    cx = err_box["x"] + err_box["width"] / 2 + random.uniform(-3, 3)
    cy = err_box["y"] + err_box["height"] / 2 + random.uniform(-2, 2)
    page.mouse.move(cx, cy)
    time.sleep(random.uniform(0.15, 0.35))
    page.mouse.down()
    time.sleep(random.uniform(0.05, 0.12))
    page.mouse.up()
    print("[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……")

    # 等滑块重新渲染出来
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _find_slider(page, sels):
            print("[solve] 滑块已重新渲染")
            return True
        page.wait_for_timeout(400)
    print("[solve] 点击后滑块未重渲")
    return False


def solve_with_retry(page, selectors: list = None, success_selector: str = None) -> bool:
    """
    滑块兜底（含失败重试，按实操经验）：
        第1次回放失败 → 换一条轨迹原地重试；
        再失败 → 刷新页面，重新等滑块、重新量距，最后试一次；
        三次都失败才放弃。
    success_selector: 验证通过后真实页的标志元素（如 1688 的 buyer-workbench），
        用于严格判定，避免把"滑块报错短暂隐藏"误判为通过。
    返回 True = 滑块已通过（或页面上本就没有滑块）。
    """
    sels = selectors or ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    tracks = load_tracks()
    used = []
    for attempt in range(1, 4):
        if attempt == 3:
            print("[solve] 第2次仍失败，刷新页面重新等滑块……")
            try:
                page.reload(timeout=20000)
            except Exception:
                pass
            # 刷新后滑块重渲需要时间（代理下更慢），轮询等待而不是固定 3s
            deadline = time.time() + 10
            while time.time() < deadline and not _find_slider(page, sels):
                page.wait_for_timeout(500)
        # 状态判断：需要点击重置（"验证失败，点击框体重试"）就先点击，
        # 可拖动就直接拖——两种状态不同策略
        if not _click_retry_if_needed(page, sels):
            found = _find_slider(page, sels)
            if not found:
                # 既无滑块也无重试框：可能真过了，也可能页面还在加载/渲染，
                # 用全量滑块信号（把手+关键词）复核，避免把加载中误判为通过
                if not _slider_present(page, sels):
                    return True
                continue   # 有滑块信号但定位不到把手：下一轮再试
        found = _find_slider(page, sels)
        if not found:
            if not _slider_present(page, sels):
                return True   # 滑块消失且无残留信号：通过
            continue
        fr, sel, box = found
        distance = _measure_distance(fr, box)
        pool = [t for t in tracks if t not in used] or tracks
        track = random.choice(pool)
        used.append(track)
        print(f"[solve] 第 {attempt} 次尝试：回放 {len(track)} 点轨迹，距离 {distance:.0f}px")
        try:
            replay_track(page, sel, distance, track=track)
        except Exception as e:
            print(f"[solve] 回放异常: {type(e).__name__}: {e}")
        if _judge_result(page, sels, success_selector=success_selector):
            print(f"[solve] ✓ 第 {attempt} 次尝试通过")
            return True
        print(f"[solve] 第 {attempt} 次失败")
        page.wait_for_timeout(1500)   # 等滑块复位再重试
    return False


def try_solve_slider(page, distance: float = 0,
                     selectors: list = None, wait_ms: int = 800) -> bool:
    """
    检测页面上是否存在滑块，发现即用真人轨迹回放拖动。
    每层内部含失败重试（换轨迹 → 刷新再试）；过完一关全页扫描，
    模态框/嵌套组件里还有滑块会继续打（多层滑块循环）。

    参数:
        distance:  保留参数（兼容旧调用）；距离现在自动测量
        selectors: 把手选择器列表，默认内置阿里系选择器
    返回:
        True = 页面已无滑块；False = 没有滑块可打，或打不动
    """
    sels = tuple(selectors) if selectors else ("[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")
    if not _slider_present(page, sels):
        return False   # 页面上没有滑块，与旧语义一致
    return solve_all_sliders(page, selectors=selectors)


# ---------------------------------------------------------------- CLI

def _test_replay(url: str, selector: str, distance: float):
    browser = _launch_guarded(headless=False)
    page = browser.new_page()
    page.goto(url)
    page.wait_for_timeout(1500)
    replay_track(page, selector, distance)
    page.wait_for_timeout(3000)   # 留时间观察校验结果
    browser.close()


def main():
    ap = argparse.ArgumentParser(description="真人轨迹 录入/回放（CloakBrowser）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="headed 录入手工拖动轨迹")
    p_rec.add_argument("--url", required=True, help="含滑块的目标页面")
    p_rec.add_argument("--max", type=int, default=20, help="最多录多少条")

    p_auto = sub.add_parser("record-auto", help="自动等滑块出现 + 自动保存轨迹（无需终端交互）")
    p_auto.add_argument("--url", required=True)
    p_auto.add_argument("--max", type=int, default=5)
    p_auto.add_argument("--timeout", type=int, default=240, help="总超时秒数")

    p_rep = sub.add_parser("replay", help="测试回放一条轨迹")
    p_rep.add_argument("--url", required=True)
    p_rep.add_argument("--selector", required=True, help="滑块把手 CSS 选择器")
    p_rep.add_argument("--distance", type=float, required=True, help="拖动距离 px")

    p_repa = sub.add_parser("replay-auto", help="全自动回放测试：等滑块→量距离→回放→判定")
    p_repa.add_argument("--url", required=True)
    p_repa.add_argument("--timeout", type=int, default=180, help="总超时秒数")

    args = ap.parse_args()
    if args.cmd == "record":
        record_tracks(args.url, args.max)
    elif args.cmd == "record-auto":
        record_tracks_auto(args.url, args.max, args.timeout)
    elif args.cmd == "replay-auto":
        replay_auto(args.url, args.timeout)
    else:
        _test_replay(args.url, args.selector, args.distance)


if __name__ == "__main__":
    main()
