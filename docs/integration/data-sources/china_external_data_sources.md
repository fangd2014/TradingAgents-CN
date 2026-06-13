# 中国外部数据源增强说明

本文档说明 A 股外部数据增强的默认来源、注册要求和降级策略。

## 数据源映射

| 能力 | 默认来源 | 注册要求 | 配置 |
| --- | --- | --- | --- |
| 行情数据 | `external_quotes` 聚合 Tencent + mootdx | 不需要注册 | `DEFAULT_CHINA_DATA_SOURCE=external_quotes`, `TENCENT_FINANCE_ENABLED`, `MOOTDX_ENABLED`, `MOOTDX_DEEP_MARKET_ENABLED` |
| 研报数据 | 东方财富 reportapi 直连 | 不需要注册 | `EASTMONEY_REPORTAPI_ENABLED` |
| 语义搜索 | pywencai + i问财 Cookie | 需要网页登录 Cookie | `IWENCAI_COOKIE` |
| 热点归因/题材 tags | 同花顺热点语义查询 | 需要 i问财 Cookie | `THS_HOTSPOT_ENABLED`, `THS_TAGS_ENABLED`, `IWENCAI_COOKIE` |
| 新闻数据 | AKShare 个股新闻、财联社快讯、东财全球资讯 | 不需要注册 | `AKSHARE_NEWS_ENABLED` |
| 公告数据 | 巨潮 cninfo + mootdx F10 摘要 | 不需要注册 | `CNINFO_ANNOUNCEMENTS_ENABLED` |

## 注册和账号入口

- mootdx: 不需要 API 注册。PyPI: <https://pypi.org/project/mootdx/>，GitHub: <https://github.com/mootdx/mootdx>。当前 `mootdx.com` 域名状态不稳定，不作为注册入口。
- 腾讯财经行情: 不提供官方开放 API Key 注册。当前实现使用公开行情端点，需按非官方接口对待。
- 东方财富 reportapi: 不需要注册。PDF 下载需要 `Referer: https://data.eastmoney.com/report/`。
- AKShare 新闻/巨潮公告: 不需要注册。AKShare 文档: <https://akshare.akfamily.xyz/data/stock/stock.html>。
- i问财 / pywencai: 不走 OpenAPI/X-Claw。标准做法是安装 `pywencai`，登录 <https://www.iwencai.com/>，从浏览器网络请求头复制 `Cookie` 字段填入 `IWENCAI_COOKIE`。pywencai README 说明当前 `cookie` 参数必填。
- 同花顺官方数据接口: 若需要官方授权或试用，申请入口可从 <https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center.html> 进入，页面提供“申请试用”和登录入口。

无法由脚本代办的注册步骤：手机号/企业信息/验证码/合同或付费授权。这类凭据拿到后填入 `.env`:

```bash
IWENCAI_COOKIE=...
```

## 新增 API

- `GET /api/china-data/source-status`
- `GET /api/china-data/quotes?codes=000001,600000`
- `GET /api/china-data/mootdx/{symbol}/order-book`
- `GET /api/china-data/mootdx/{symbol}/kline?period=day`
- `GET /api/china-data/mootdx/{symbol}/transactions`
- `GET /api/china-data/mootdx/{symbol}/finance`
- `GET /api/china-data/mootdx/{symbol}/f10?category=公司概况`
- `GET /api/china-data/research-reports/{symbol}?limit=20`
- `GET /api/china-data/research-reports/{symbol}/pdf-meta`
- `GET /api/china-data/semantic-search?q=人工智能%20近5日涨幅`
- `GET /api/china-data/hotspots`
- `GET /api/china-data/theme-tags/{symbol}`
- `GET /api/china-data/news/{symbol}`
- `GET /api/china-data/news/cls-flash/latest`
- `GET /api/china-data/news/global/latest`
- `GET /api/china-data/announcements/{symbol}`
- `POST /api/favorites/enrich-latest-sources`

所有接口需要现有登录鉴权。

## 配置和维护脚本

默认配置已经切到:

```bash
DEFAULT_CHINA_DATA_SOURCE=external_quotes
TUSHARE_ENABLED=false
QUOTES_AUTO_DETECT_TUSHARE_PERMISSION=false
TUSHARE_QUOTES_SYNC_ENABLED=false
```

更新 Mongo 中的系统配置和补全已有自选股:

```bash
./.venv-api/bin/python scripts/update_china_data_sources_and_enrich_favorites.py
```

脚本会写入 7 个模块和 1 个聚合行情入口：`External Quotes`, `Tencent Finance`, `mootdx`, `Eastmoney ReportAPI`, `iWenCai pywencai`, `THS Hotspot Tags`, `AKShare News Trio`, `Cninfo Announcements`。

## 降级策略

- 行情富集只走 Tencent/mootdx，不再降级到 AKShare 行情。
- 行情入库只走 `external_quotes`。该通道依赖本地 `stock_basic_info` 股票代码列表，再批量调用 Tencent/mootdx。
- i问财和题材 tags 在缺少 `IWENCAI_COOKIE` 或 `pywencai` 未安装时返回 `available=false` 和原因，不阻断主流程。

## 可选运行依赖

本次接入未把 `mootdx` 强加为必装依赖。需要启用深行情时安装:

```bash
pip install mootdx
```

i问财语义搜索依赖 pywencai 和本机 Node.js v16+:

```bash
pip install pywencai
```
