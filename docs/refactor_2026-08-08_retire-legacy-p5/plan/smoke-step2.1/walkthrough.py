# Step 2.1 走查：wa 表单裁剪 + 删从命令导入 + api.ts 失配修复
# 对 http://127.0.0.1:3000（vite dev，HMR 已热载新代码）真实浏览器走查并截图
import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:3000"
OUT = Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)

TYPE_LABELS = {
    "wa_check": "WhatsApp 查号",
    "yiwugo_search": "义乌购搜索",
    "1688_contact": "1688 联系方式采集",
}


async def pick_type(page, label: str):
    """在任务类型下拉中选中指定类型（radix select：trigger + portal option）。"""
    # 对话框内有两个 Select（模板加载 / 任务类型）：任务类型在其 Label 的父 div 内
    type_label = page.locator("label", has_text="任务类型")
    trigger = type_label.locator("xpath=..//button").first
    await trigger.click()
    # radix option 在 portal 中渲染，按文本定位
    opt = page.locator("[role=option]", has_text=label).first
    await opt.click()
    await page.wait_for_timeout(400)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(15000)

        # ---------- 场景 1：wa_check 新表单 ----------
        await page.goto(f"{BASE}/tasks")
        await page.wait_for_load_state("networkidle")
        await page.get_by_role("button", name="新建任务").click()
        await page.wait_for_timeout(600)
        await pick_type(page, TYPE_LABELS["wa_check"])
        await page.wait_for_timeout(600)
        # 断言：无已删字段
        body = await page.locator("body").inner_text()
        assert "每批查号数量" not in body, "每批查号数量 应已删除"
        assert "查号间隔" not in body, "查号间隔 应已删除"
        assert "批间休息" not in body, "批间休息 应已删除"
        assert "从命令导入" not in body, "从命令导入 应已删除"
        await page.screenshot(path=str(OUT / "1-wa-new-form.png"))
        print("[1] wa_check 新表单：仅 查号上限 + 查号账号，无已删字段 ✓")
        await page.get_by_role("button", name="取消").click()
        await page.wait_for_timeout(400)

        # ---------- 场景 2：编辑历史任务 73（含旧字段） ----------
        # 定位 id=73 所在行（第 2 列）并点「编辑」
        row = page.locator("tbody tr").filter(
            has=page.locator("td:nth-child(2)", has_text="#73")
        ).first
        await row.get_by_role("button", name="编辑").click()
        await page.wait_for_timeout(800)
        body = await page.locator("body").inner_text()
        assert "编辑任务 #73" in body, "应打开编辑任务 #73 对话框"
        assert "每批查号数量" not in body and "查号间隔" not in body and "批间休息" not in body
        # limit 为空（limit=null），账号 xiaohao-4 勾选
        limit_input = page.locator("#wa-limit")
        limit_val = await limit_input.input_value()
        assert limit_val == "", f"limit 应为空，实际 {limit_val!r}"
        acc_check = page.locator("#wa-acc-xiaohao-4")
        assert await acc_check.is_checked(), "xiaohao-4 应勾选"
        await page.screenshot(path=str(OUT / "2-wa-edit-task73.png"))
        print("[2] 编辑任务 #73：limit 空 + xiaohao-4 勾选，旧字段不展示、无报错 ✓")
        await page.get_by_role("button", name="取消").click()
        await page.wait_for_timeout(400)

        # ---------- 场景 3：yiwugo_search 全表单 ----------
        await page.get_by_role("button", name="新建任务").click()
        await page.wait_for_timeout(600)
        await pick_type(page, TYPE_LABELS["yiwugo_search"])
        await page.wait_for_timeout(600)
        # 高级参数默认折叠，展开后再断言完整字段
        await page.get_by_role("button", name="高级参数").click()
        await page.wait_for_timeout(500)
        body = await page.locator("body").inner_text()
        for expect in ["每批数量", "取样下限", "取样上限", "代理通道", "高级参数", "批间休息"]:
            assert expect in body, f"yiwugo 表单应含 {expect}"
        await page.screenshot(path=str(OUT / "3-yiwugo-full-form.png"))
        print("[3] yiwugo_search：完整表单（每批数量/取样/代理通道/高级参数）✓")
        await page.get_by_role("button", name="取消").click()
        await page.wait_for_timeout(400)

        # ---------- 场景 4：1688_contact 批次表单 ----------
        await page.get_by_role("button", name="新建任务").click()
        await page.wait_for_timeout(600)
        await pick_type(page, TYPE_LABELS["1688_contact"])
        await page.wait_for_timeout(600)
        body = await page.locator("body").inner_text()
        assert "采集上限" in body and "循环间隔" in body, "批次表单应含 采集上限 + 循环间隔"
        assert "高级参数" not in body, "批次表单不应有 高级参数"
        await page.screenshot(path=str(OUT / "4-batch-1688-contact.png"))
        print("[4] 1688_contact 批次表单：采集上限 + 循环间隔 ✓")

        await browser.close()
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
