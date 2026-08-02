#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐条测试轨迹库：每条轨迹开独立会话，等滑块→量距→用指定轨迹回放→判定。"""

import sys, time
sys.path.insert(0, str(__file__.rsplit("/", 2)[0] + "/util"))
from slider_track import (_launch_guarded, _find_slider, replay_track,
                          load_tracks, TRACKS_FILE)

URL = "https://shop5893dbu066953.1688.com/page/contactinfo.htm"
PER_TRACK_TIMEOUT = 90

tracks = load_tracks()
print(f"共 {len(tracks)} 条轨迹待测试\n")
results = []

for i, track in enumerate(tracks):
    print(f"===== 测试第 {i+1} 条（{len(track)}点）=====")
    browser = _launch_guarded(headless=False)
    page = browser.new_page()
    deadline = time.time() + PER_TRACK_TIMEOUT
    found = None
    while time.time() < deadline and not found:
        try:
            page.goto(URL, timeout=20000)
        except Exception as e:
            if "TargetClosed" in type(e).__name__:
                print("  会话被终止，跳过本条"); break
        page.wait_for_timeout(2500)
        found = _find_slider(page)
        if not found:
            print("  未弹滑块，3s 后刷新……")
            page.wait_for_timeout(3000)
    if not found:
        print("  ✗ 超时未等到滑块，本条无法判定\n")
        results.append((i + 1, "未判定"))
        try: browser.close()
        except Exception: pass
        continue

    fr, sel, box = found
    distance = None
    for tsel in ("[id$='__scale_text']", "[id$='__bg']"):
        try:
            tb = fr.locator(tsel).first.bounding_box()
            if tb:
                distance = tb["width"] - box["width"]; break
        except Exception: pass
    distance = distance or 300
    print(f"  滑块出现，回放距离 {distance:.0f}px ……")
    try:
        replay_track(page, sel, distance, track=track)
        page.wait_for_timeout(2500)
        ok = not _find_slider(page)
    except Exception as e:
        print(f"  回放异常: {type(e).__name__}"); ok = False
    print(f"  {'✓ 验证通过' if ok else '✗ 验证失败'}\n")
    results.append((i + 1, "通过" if ok else "失败"))
    try: browser.close()
    except Exception: pass
    page.wait_for_timeout(1000) if False else time.sleep(2)

print("===== 汇总 =====")
for n, r in results:
    print(f"  第{n}条: {r}")
