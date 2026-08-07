# Step 2.2 Report — 隔离性单测（identity 分桶 P2 Phase 2 最后一步）

> 日期：2026-08-08 | 分支：feat/fetcher-identity-p2 | Commit：8782609

## 内容

新增 `fetcher/tests/test_identity_isolation.py`（320 行，单文件），13 个测试验证**同 IP 两站点 Cookie / 事件 / 簿记 / 内存键互不污染**（SPEC §5 第 2、3 条达成）。

## 用例清单与结果（①-⑥）

| # | 用例 | 断言要点 | 结果 |
|---|------|---------|------|
| ① | Cookie 各落各桶、load 不串 | 1688 store 存 `1688:1.2.3.4` → 只含 1688 域 Cookie；mic store 存 `madeinchina:1.2.3.4` → 只含 mic 域 Cookie；1688 键不含 PHPSESSID，mic 键不含 cna/_csrf | ✅ |
| ② | burn 一站不殃及另一站 | burn `1688:1.2.3.4` → 1688 桶空（n=2），mic 桶完好（1 条，value="from-mic"） | ✅ |
| ③a | ip_events 分行统计 | 同裸 IP 两站点各 record_event → 两行不同 identity，1688 行 event=block_slider/re_since_block=3，mic 行 event=launch/re_since_block=None | ✅ |
| ③b | ip_stats 分行统计 | 1688 12 请求 8 成功，mic 6 请求 5 成功，互不相干；只给 1688 记 block → mic blocks=0 | ✅ |
| ④a | ip_req 键分开 | dict 按 `1688:1.2.3.4` 键计数 n=2/since=1，`madeinchina:1.2.3.4` 键不在 dict 中 | ✅ |
| ④b | budget_stuck 键分开 | set 加 `1688:1.2.3.4` → `madeinchina:1.2.3.4` 不在 set 中 | ✅ |
| ④c | burn_ips 键分开 | SeedBurnTracker.note_block(`1688:1.2.3.4`) → burn_ips 含之，`madeinchina:1.2.3.4` 不在 | ✅ |
| ⑤a | 指纹同裸 IP 一致 | fingerprint_args(bare_identity("1688:1.2.3.4")) == fingerprint_args("1.2.3.4") == fingerprint_args(bare_identity("madeinchina:1.2.3.4")) | ✅ |
| ⑤b | 不同 IP 指纹不同 | fingerprint_args("1.2.3.4") != fingerprint_args("5.5.5.5") | ✅ |
| ⑥a | check_ip_fresh 1688:ip 判相等 | mock 出口 IP=1.2.3.4，Session(identity="1688:1.2.3.4") → need=False | ✅ |
| ⑥b | check_ip_fresh bare IP 判相等 | Session(identity="1.2.3.4") → need=False（回归） | ✅ |
| ⑥c | check_ip_fresh mic:ip 判相等 | Session(identity="madeinchina:1.2.3.4") → need=False | ✅ |
| ⑥d | 三种形式等效 | for identity in ("1.2.3.4", "1688:1.2.3.4", "madeinchina:1.2.3.4") → 均 need=False | ✅ |

## 定向破坏证据

### RED（破坏 burn 隔离断言）

**改动**：`test_burn_isolation` 中将 `assertEqual(len(loaded_mic), 1)` 改为 `assertEqual(len(loaded_mic), 99)`。

**命令**：
```
cd fetcher && python -m pytest tests/test_identity_isolation.py::IdentityIsolationDBTest::test_burn_isolation -v
```

**失败输出**：
```
FAILED tests/test_identity_isolation.py::IdentityIsolationDBTest::test_burn_isolation

AssertionError: 1 != 99 : [定向破坏] 故意错误断言 mic 桶有 99 条 Cookie
```

说明：burn 1688 桶后 mic 桶实际仍有 1 条 Cookie（值 "from-mic"），故意断言 99 条 → `1 != 99` 失败，**证明测试真的在检测跨站隔离**。

### GREEN（恢复正确断言）

恢复 `assertEqual(len(loaded_mic), 1)` 后：
```
13 passed in 0.06s
```

## 全量测试

```
cd fetcher && python -m pytest tests -x -q
303 passed, 2 subtests passed in 15.23s
```

基线 290 → 新增 13 → 总计 303，无回归。

## 改动文件

```
fetcher/tests/test_identity_isolation.py  (新增, +320 行)
```

无其他文件修改。无生产代码改动。未碰生产库。

## 自查

- `git status` 确认：仅 `fetcher/tests/test_identity_isolation.py` 在新 commit 中
- `git diff --cached --stat` 确认：单文件 320 行
- 未碰 `fetcher/fetcher/` 生产代码
- 未碰 `platform/`
- 不做 Step 3（冒烟）——下一步

## 疑虑

无。所有用例均按 brief ①-⑥ 实现，定向破坏 RED/GREEN 完整，全量无回归。
