# China External Data Sources Design

## Purpose

接入用户指定的四类 A 股外部数据能力：

- 行情数据：mootdx 深行情 + 腾讯财经指标
- 研报数据：东方财富 reportapi + 机构预期
- 语义搜索：pywencai + i问财 Cookie
- 热点归因：同花顺当日强势股 + 题材 tags
- 新闻数据：AKShare 个股新闻、财联社快讯、东财全球资讯
- 基础/公告：mootdx finance/F10 + 巨潮 cninfo

## Design

新增 `app.services.china_external_data_service` 作为统一门面。所有外部源都作为可选增强能力接入，失败时返回结构化不可用状态或降级到既有数据源，不阻断主分析流程。

行情路径分两层：

- `QuotesService` 的筛选富集只用 Tencent/mootdx，不再回落到 AKShare 行情。
- `QuotesIngestionService` 的定时入库只走 `external_quotes`，通过本地 `stock_basic_info` 代码列表批量拉取 Tencent/mootdx。

研报路径通过东方财富 `reportapi` 直连读取研报列表、三年 EPS 预测和 PDF 地址；PDF 下载使用东财研报页 Referer。

i问财和同花顺 tags 共享 `pywencai` 与 `IWENCAI_COOKIE`。未配置 Cookie 或未安装 pywencai 时返回 `available=false`，避免分析任务因账号问题失败。

新闻与公告保持低频调用：AKShare 只用于新闻三件套和巨潮 cninfo 公告，不用于行情。

## Registration

- mootdx：不需要注册，项目主页 <https://www.mootdx.com/>。
- 腾讯财经：无官方开放 API Key 注册，本实现使用公开行情端点。
- 东方财富 reportapi：不需要注册。
- AKShare 新闻/巨潮公告：不需要注册，文档 <https://akshare.akfamily.xyz/data/stock/stock.html>。
- i问财 / pywencai：不走 OpenAPI/X-Claw；登录 <https://www.iwencai.com/> 后复制浏览器请求头 Cookie，填入 `IWENCAI_COOKIE`。
- 同花顺官方接口：如需官方授权，入口 <https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center.html>。

## Testing

新增 `tests/services/test_china_external_data_sources.py` 覆盖：

- 腾讯行情字段解析
- 腾讯指标字段解析
- 东方财富 reportapi EPS/PDF 标准化
- i问财 pywencai Cookie 鉴权
- 同花顺热点归因字段抽取
- AKShare 新闻三件套标准化
- 巨潮公告标准化
- mootdx 深行情调用委派
- AKShare 行情不再兜底
