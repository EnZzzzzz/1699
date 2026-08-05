# 联系方式采集源调研：1688 国际站 与 中国制造网

> 日期：2026-08-05　状态：**调研完成，中国制造网中文站可采集**（未实现）
> 目的：评估为现有 1688 联系方式采集扩源的可行性。

---

## 1. 结论速览

为现有 1688 国内版（`contactinfo.htm` 电话/手机/传真/地址/联系人）扩源做可行性调研，结论如下：

| 平台 | 手机号 | 邮箱 | 地址 | 采集难度 | 结论 |
|---|---|---|---|---|---|
| 1688 国内版 `shopxxx.1688.com/page/contactinfo.htm` | ✅ 公开 | — | ✅ | 中（x5sec 滑块风控，需养身份/代理） | 现有采集器已采 |
| 1688 国际版 `en.1688.com` | ✅ 公开 | — | ✅ | 与国内版相同 | **无新增价值**：同一平台/同一批店铺/同一联系方式页 |
| 阿里巴巴国际站 `alibaba.com` | ❌ | ❌ | ⚠️ 仅省级 | 极高（登录后仍不可见） | **不值得做**，联系方式完全封死 |
| 中国制造网 **中文站** `cn.made-in-china.com` | ✅ **写在 SEO meta description 里** | — | ✅ 街道级 | **低** | **✅ 值得做，是本次调研的落点** |
| 中国制造网国际站 `en.made-in-china.com` | ❌ | ❌ | ✅ 街道级 | 高 | 不做（需询盘/聊天才给） |

**一句话结论**：真正可扩源且成本低的是 **中国制造网中文站**——手机号直接写死在联系方式页的 `<meta name="Description">` 里，免登录、免点击、免接口。**但注意**：实测这批中文站供应商 WhatsApp 注册率仅 ~7%（见 §3.6），若触达目标是 WhatsApp 则价值有限。

---

## 2. 各平台实测证据（2026-08-05 浏览器实机验证）

### 2.1 中国制造网中文站 `cn.made-in-china.com` —— 可采

**联系方式页 URL 模式**：`https://cn.made-in-china.com/showroom/{子域名}-contact.html`

页面关键结构（GBK 编码）：

```html
<!-- 页面正文直接可见：地址、联系人、部分供应商的传真 -->
传真：0769-82367598
地址：广东省 东莞市 桥头镇 中国广东省东莞市桥头禾坑和里新村122
赵女士（业务员）

<!-- 手机号写死在 SEO meta 里（提取只需正则） -->
<meta name="Description" content="中国制造网，东莞市桥头迪贺五金制品厂，联系人：赵，联系电话：13728319349">
```

页面上的「查看电话号码」按钮只是 JS 展开（`fix-view-tel` 结构），号码本就在源码里，点开不会触发登录。

**批量实证**：从五金工具 market 页捞 76 家供应商，**75 家（99%）meta 里都有完整手机号**。样例数据：`.cache/mic_contacts_20260805.json`。

### 2.2 中国制造网国际站 `en.made-in-china.com` —— 不可采

登录账号后访问 `{company}.en.made-in-china.com/contact-info.html`，实测（供应商 lvtong 等）：

- 无 tel:/mailto: 链接，正文/网络请求均无电话/邮箱/WhatsApp
- 只显示：联系人姓名/部门/职位 + 街道级地址 + 展厅 URL
- 联系必须走 Send Inquiry / Chat Now，与 [Apify made-in-china scraper](https://apify.com/bovi/made-in-china-scraper) 记载一致（phone/email/WhatsApp 在登录墙后）

### 2.3 阿里巴巴国际站 `alibaba.com` —— 不可采

登录国际站账号（en ze）后，实测 2 家供应商（`hk-promotion-gift` 义乌鸿金棉布袋、`gzydpj` 广州艺代皮具）的「公司概述」+「公司档案 `company_profile.html`」两页：

- 无 tel:/mailto: 链接、无明文/打码邮箱、无手机号、无 WhatsApp
- 网络请求无联系方式接口（全是 onetalk 聊天 / 埋点 / 视频 / CDN）
- 地址仅省级（"Guangdong, China"），无街道级
- 只有「联系供应商 / 立即联系」按钮 → 询盘/聊天才给联系方式

### 2.4 1688 国际版 `en.1688.com` —— 与国内版同源

1688 国际版只是多语言浏览界面，底层同一批 `shopxxx.1688.com` 店铺，联系方式页仍是 `shopxxx.1688.com/page/contactinfo.htm`，字段与国内版一致。现有 `ContactTask` 直接复用即可，无新增成本。

---

## 3. 中国制造网中文站采集方法（方案）

### 3.1 步骤总览

```
① 发现子域名：market 页 / 搜索页 → {子域名}.cn.made-in-china.com
② 拼接联系方式页：https://cn.made-in-china.com/showroom/{子域名}-contact.html
③ GET + 按 GBK 解码
④ 正则提取 <meta name="Description"> 的 联系电话 + 页面正文的 地址/传真/联系人
⑤ 手机号规范化为 E.164（补 86）→ 供 WhatsApp 查号
```

### 3.2 供应商子域名发现

产品 market 页一页能捞 30-40 个子域名：

```
https://cn.made-in-china.com/market/{类目slug}_2-{页码}.html
# 例：五金工具 wujingj 第 1-3 页 → 87 个子域名
```

页面里 `https://{sub}.cn.made-in-china.com/` 即为供应商展厅子域名。也可用站内搜索页（`companysearch.do` / `productdirectory.do`）发现。

### 3.3 手机号提取（核心）

```python
import requests, re

r = requests.get(f"https://cn.made-in-china.com/showroom/{sub}-contact.html",
                 headers={"User-Agent": UA}, timeout=20)
r.encoding = "gbk"                       # 关键：页面是 GBK，必须显式解码
m = re.search(r'<meta name="Description" content="([^"]+)"', r.text)
desc = m.group(1) if m else ""
tel = re.search(r'联系电话[：:]\s*([0-9\-\s]+)', desc)
phone = tel.group(1).strip() if tel else None
```

浏览器会话内用 `fetch()` 时同理，需 `new TextDecoder('gbk').decode(arrayBuffer)`，否则中文字段变乱码导致正则失配。

### 3.4 可一并采集的字段

| 字段 | 来源 | 说明 |
|---|---|---|
| 手机号 | `<meta name="Description">` | 完整，实测命中率 99% |
| 联系人（姓） | meta description + 页面正文 | 部分脱敏，只给姓（如"赵"） |
| 地址 | 页面正文「地址：」行 | 街道级 |
| 传真 | 页面正文「传真：」行 | 部分供应商公开（实测 0769-82367598） |

### 3.5 反爬：vemic FCaptcha

- 快速连刷（实测 ~80 次 / 0.3s 间隔）会触发 **vemic FCaptcha** 验证页：`captcha.vemic.com`，标题「请验证」，UTF-8，body 长度 ≈4400
- 慢速 + 浏览器会话（带验证 cookie）基本不触发：浏览器内 `fetch()` 批量拉 80 页无拦截
- 实现时需：请求间隔（建议 ≥1s）、异常时识别验证页特征（`vemic` / 长度 < 5000）并退避重试

### 3.6 WhatsApp 查号衔接

- 手机号统一补 `86` 前缀 → E.164（如 `13728319349` → `8613728319349`），直接喂现有 `wa_tasks` / `CheckWhatsApp` 原子

**实测注册率（2026-08-05，xiaohao-2 账号，74 个号码 0 失败）：**

- ✅ 已注册 WhatsApp **5 / 74（6.6%）**，❌ 未注册 69
- 已注册的 5 家：东莞川朴精密五金（13712728166）、广东欣阳包装（13724036498）、上海沣会工业（13918666153）、山东中驰机械（15665732536）、惠州铭羽杰精密（15875217180）
- 结果文件：`/tmp/mic_wa_results.json`

**对采集价值的判断**：中文站供应商留的基本是国内手机号，**绑 WhatsApp 的只有个位数**。若平台目标是「采号 → WhatsApp 触达」，本数据源价值低——号好采（99%）但注册率仅 ~7%。若要与内贸数据对比，可看 1688 国内供应商的 WhatsApp 注册率是否同样偏低。

### 3.7 与 fetcher 框架的接入（后续实现时）

- 新增 `fetcher/sites/madeinchina/` 站点插件：`shop`（子域名发现）+ `contact`（联系方式提取），复用 `core` 的 `ActionResult/Outcome/WorkerContext`
- 反爬处置走既有 `strategy` 链（识别 vemic 验证页 = blocked 场景）
- 平台侧 `platform/server/app/tasks.py` + `runner.py` 注册任务类型；写库沿用 `app.db` 短事务约定
- 页面为 GBK：抓取 atom 内显式 `decode('gbk')`，提取后统一 UTF-8 入库（与 1688 一致）

---

## 4. 关联

- 实抓样例数据：`.cache/mic_contacts_20260805.json`（76 供应商 / 75 有手机号）
- 待查号码：`/tmp/mic_numbers.txt`（74 个 E.164）
- 1688 现有采集：`fetcher/fetcher/sites/alibaba1688/contact.py`
