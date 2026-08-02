#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断脚本：定位 1688 验证页滑块的真实宿主（frame / shadow DOM），排查轨迹录制不到的原因。"""

import sys
import time

URL = "https://shop5893dbu066953.1688.com/page/contactinfo.htm"

from cloakbrowser import launch

browser = launch(headless=False)
page = browser.new_page()
page.goto(URL)
page.wait_for_timeout(4000)

print("=" * 70)
print("1. 页面 frame 清单")
for fr in page.frames:
    print(f"   [{fr.url[:90]}]")

print("=" * 70)
print("2. 在主文档和各 frame 里找滑块把手 / 轨道")
HANDLE_CANDIDATES = [
    "[id$='_n1z']", ".nc_iconfont.btn_slide", "#nc_1_n1z",
    ".btn_slide", "[class*='btn_slide']", ".nc-lang-cnt",
]
TRACK_CANDIDATES = ["[id$='__scale_text']", "[id$='__bg']", ".nc_scale_text", "[class*='scale']"]

for fr in page.frames:
    print(f"\n--- frame: {fr.url[:70]} ---")
    for sel in HANDLE_CANDIDATES:
        try:
            loc = fr.locator(sel).first
            if loc.count():
                box = loc.bounding_box()
                vis = loc.is_visible()
                print(f"   把手命中: {sel}  visible={vis}  box={box}")
        except Exception as e:
            print(f"   把手 {sel} 出错: {type(e).__name__}")
    for sel in TRACK_CANDIDATES:
        try:
            loc = fr.locator(sel).first
            if loc.count():
                box = loc.bounding_box()
                print(f"   轨道命中: {sel}  box={box}")
        except Exception:
            pass

print("\n" + "=" * 70)
print("3. nocaptcha 容器结构（主文档 #nocaptcha 内部 HTML 片段）")
try:
    html = page.evaluate("""() => {
        const el = document.querySelector('#nocaptcha');
        return el ? el.innerHTML.slice(0, 1500) : '(无 #nocaptcha)';
    }""")
    print(html[:1500])
except Exception as e:
    print(f"   读取失败: {e}")

print("\n" + "=" * 70)
print("4. 检查 shadow DOM / iframe 嵌套")
info = page.evaluate("""() => {
    const out = [];
    // 找页面里所有 iframe
    document.querySelectorAll('iframe').forEach(f =>
        out.push('iframe: ' + (f.id || f.name || f.src || '(no id/src)').slice(0, 80)));
    // 找带 shadowRoot 的元素
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_ELEMENT);
    let n = 0;
    while (walker.nextNode() && n < 2000) {
        n++;
        if (walker.currentNode.shadowRoot)
            out.push('shadowRoot: <' + walker.currentNode.tagName + '> id=' + walker.currentNode.id);
    }
    return out;
}""")
for line in info:
    print(f"   {line}")

print("\n" + "=" * 70)
print("5. 模拟一次 CDP 拖动，验证监听能否抓到（注入捕获阶段监听后自动拖）")
page.evaluate("""() => {
    window.__track = []; window.__recording = false;
    ['mousedown','pointerdown'].forEach(ev => document.addEventListener(ev, () => {
        window.__recording = true; window.__track = [];
    }, true));
    document.addEventListener('mousemove', e => {
        if (window.__recording) window.__track.push([e.clientX, e.clientY, performance.now()]);
    }, true);
    ['mouseup','pointerup'].forEach(ev => document.addEventListener(ev, () => {
        window.__recording = false;
    }, true));
    return 'injected';
}""")

# 尝试找到把手坐标并模拟拖动
target = None
for fr in page.frames:
    for sel in HANDLE_CANDIDATES:
        try:
            loc = fr.locator(sel).first
            if loc.count() and loc.is_visible():
                target = loc.bounding_box()
                print(f"   用 {sel} @ frame[{fr.url[:40]}] 模拟拖动, box={target}")
                break
        except Exception:
            pass
    if target:
        break

if target:
    sx, sy = target["x"] + target["width"]/2, target["y"] + target["height"]/2
    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, 21):
        page.mouse.move(sx + i * 14, sy + (i % 3 - 1))
        time.sleep(0.02)
    page.mouse.up()
    time.sleep(0.5)
    n = page.evaluate("window.__track.length")
    print(f"   模拟拖动后主文档采样点: {n}")
    if n > 0:
        t = page.evaluate("window.__track")
        print(f"   首点 {t[0]}, 末点 {t[-1]}")
else:
    print("   未找到可见把手，无法模拟拖动")

print("\n" + "=" * 70)
print("6. 截图存档")
page.screenshot(path="util/_diag_slider.png", full_page=False)
print("   已保存 util/_diag_slider.png")

page.wait_for_timeout(2000)
browser.close()
print("\n诊断完成")
