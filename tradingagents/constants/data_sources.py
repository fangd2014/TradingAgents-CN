"""
数据源编码统一定义
所有数据源的编码、名称、描述等信息都在这里定义

添加新数据源的步骤：
1. 在 DataSourceCode 枚举中添加新的数据源编码
2. 在 DATA_SOURCE_REGISTRY 中注册数据源信息
3. 在对应的 provider 中实现数据源接口
4. 更新前端的数据源类型选项（如果需要）
"""

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass


class DataSourceCode(str, Enum):
    """
    数据源编码枚举
    
    命名规范：
    - 使用大写字母和下划线
    - 值使用小写字母和下划线
    - 保持简洁明了
    """
    
    # ==================== 缓存数据源 ====================
    MONGODB = "mongodb"  # MongoDB 数据库缓存（最高优先级）
    
    # ==================== 中国市场数据源 ====================
    TUSHARE = "tushare"      # Tushare - 专业A股数据
    AKSHARE = "akshare"      # AKShare - 开源金融数据（A股+港股）
    BAOSTOCK = "baostock"    # BaoStock - 免费A股数据
    EXTERNAL_QUOTES = "external_quotes"  # Tencent/mootdx 行情聚合
    MOOTDX = "mootdx"        # mootdx - 通达信深行情
    TENCENT_FINANCE = "tencent_finance"  # 腾讯财经行情指标
    EASTMONEY_REPORTAPI = "eastmoney_reportapi"  # 东方财富研报
    IWENCAI = "iwencai"      # i问财语义搜索
    THS_HOTSPOT = "ths_hotspot"  # 同花顺热点归因
    AKSHARE_NEWS = "akshare_news"  # AKShare新闻三件套
    CNINFO = "cninfo"        # 巨潮公告
    
    # ==================== 美股数据源 ====================
    YFINANCE = "yfinance"         # yfinance - Yahoo Finance Python库
    FINNHUB = "finnhub"           # Finnhub - 美股实时数据
    YAHOO_FINANCE = "yahoo_finance"  # Yahoo Finance - 全球股票数据（别名）
    ALPHA_VANTAGE = "alpha_vantage"  # Alpha Vantage - 美股技术分析
    IEX_CLOUD = "iex_cloud"       # IEX Cloud - 美股实时数据
    
    # ==================== 港股数据源 ====================
    # 注意：AKShare 也支持港股，已在上面定义
    
    # ==================== 专业数据源 ====================
    WIND = "wind"        # Wind 万得 - 专业金融终端
    CHOICE = "choice"    # 东方财富 Choice - 专业金融数据
    
    # ==================== 其他数据源 ====================
    QUANDL = "quandl"        # Quandl - 经济和金融数据
    LOCAL_FILE = "local_file"  # 本地文件数据源
    CUSTOM = "custom"        # 自定义数据源


@dataclass
class DataSourceInfo:
    """数据源信息"""
    code: str  # 数据源编码
    name: str  # 数据源名称
    display_name: str  # 显示名称
    provider: str  # 提供商
    description: str  # 描述
    supported_markets: List[str]  # 支持的市场（a_shares, us_stocks, hk_stocks, etc.）
    requires_api_key: bool  # 是否需要 API 密钥
    is_free: bool  # 是否免费
    official_website: Optional[str] = None  # 官方网站
    documentation_url: Optional[str] = None  # 文档地址
    features: List[str] = None  # 特性列表
    
    def __post_init__(self):
        if self.features is None:
            self.features = []


# ==================== 数据源注册表 ====================
DATA_SOURCE_REGISTRY: Dict[str, DataSourceInfo] = {
    # MongoDB 缓存
    DataSourceCode.MONGODB: DataSourceInfo(
        code=DataSourceCode.MONGODB,
        name="MongoDB",
        display_name="MongoDB 缓存",
        provider="MongoDB Inc.",
        description="本地 MongoDB 数据库缓存，最高优先级数据源",
        supported_markets=["a_shares", "us_stocks", "hk_stocks", "crypto", "futures"],
        requires_api_key=False,
        is_free=True,
        features=["本地缓存", "最快速度", "离线可用"],
    ),
    
    # Tushare
    DataSourceCode.TUSHARE: DataSourceInfo(
        code=DataSourceCode.TUSHARE,
        name="Tushare",
        display_name="Tushare",
        provider="Tushare",
        description="专业的A股数据接口，提供高质量的历史数据和实时行情",
        supported_markets=["a_shares"],
        requires_api_key=True,
        is_free=False,  # 免费版有限制，专业版需付费
        official_website="https://tushare.pro",
        documentation_url="https://tushare.pro/document/2",
        features=["历史行情", "实时行情", "财务数据", "基本面数据", "新闻公告"],
    ),
    
    # AKShare
    DataSourceCode.AKSHARE: DataSourceInfo(
        code=DataSourceCode.AKSHARE,
        name="AKShare",
        display_name="AKShare",
        provider="AKFamily",
        description="开源的金融数据接口，支持A股和港股，完全免费",
        supported_markets=["a_shares", "hk_stocks"],
        requires_api_key=False,
        is_free=True,
        official_website="https://akshare.akfamily.xyz",
        documentation_url="https://akshare.akfamily.xyz/introduction.html",
        features=["历史行情", "实时行情", "财务数据", "新闻资讯", "完全免费"],
    ),
    
    # BaoStock
    DataSourceCode.BAOSTOCK: DataSourceInfo(
        code=DataSourceCode.BAOSTOCK,
        name="BaoStock",
        display_name="BaoStock",
        provider="BaoStock",
        description="免费的A股数据接口，提供稳定的历史数据",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="http://baostock.com",
        documentation_url="http://baostock.com/baostock/index.php/Python_API%E6%96%87%E6%A1%A3",
        features=["历史行情", "财务数据", "完全免费", "数据稳定"],
    ),

    DataSourceCode.EXTERNAL_QUOTES: DataSourceInfo(
        code=DataSourceCode.EXTERNAL_QUOTES,
        name="External Quotes",
        display_name="行情聚合(Tencent/mootdx)",
        provider="Tencent Finance + mootdx",
        description="A股实时行情默认低风险通道，聚合腾讯公开行情和mootdx。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        features=["实时价格", "五档盘口", "PE/PB", "市值", "换手率"],
    ),

    DataSourceCode.MOOTDX: DataSourceInfo(
        code=DataSourceCode.MOOTDX,
        name="mootdx",
        display_name="mootdx深行情",
        provider="TongDaXin public servers",
        description="通达信TCP协议，提供深行情、K线、逐笔、finance和F10。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        documentation_url="https://pypi.org/project/mootdx/",
        features=["深行情", "K线", "逐笔成交", "finance", "F10"],
    ),

    DataSourceCode.TENCENT_FINANCE: DataSourceInfo(
        code=DataSourceCode.TENCENT_FINANCE,
        name="Tencent Finance",
        display_name="腾讯财经指标",
        provider="Tencent Finance",
        description="腾讯公开行情端点，补充PE(TTM)、PB、市值、换手率和涨跌停价。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        features=["实时行情", "PE/PB", "市值", "换手率", "涨跌停价"],
    ),

    DataSourceCode.EASTMONEY_REPORTAPI: DataSourceInfo(
        code=DataSourceCode.EASTMONEY_REPORTAPI,
        name="Eastmoney ReportAPI",
        display_name="东财研报",
        provider="Eastmoney",
        description="东方财富reportapi，提供研报列表、三年EPS预测和PDF下载元数据。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="https://data.eastmoney.com/report/",
        features=["研报列表", "EPS预测", "PDF元数据"],
    ),

    DataSourceCode.IWENCAI: DataSourceInfo(
        code=DataSourceCode.IWENCAI,
        name="iWenCai pywencai",
        display_name="i问财语义搜索",
        provider="iWenCai",
        description="自然语言语义搜索，标准做法为pywencai库加登录Cookie。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="https://www.iwencai.com/",
        features=["自然语言检索", "跨主题检索", "研报语义搜索"],
    ),

    DataSourceCode.THS_HOTSPOT: DataSourceInfo(
        code=DataSourceCode.THS_HOTSPOT,
        name="THS Hotspot Tags",
        display_name="同花顺热点归因",
        provider="THS/iWenCai",
        description="同花顺题材tags和热点归因，复用pywencai与IWENCAI_COOKIE。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="https://www.iwencai.com/",
        features=["题材tags", "热点归因", "强势股"],
    ),

    DataSourceCode.AKSHARE_NEWS: DataSourceInfo(
        code=DataSourceCode.AKSHARE_NEWS,
        name="AKShare News Trio",
        display_name="AKShare新闻三件套",
        provider="AKShare",
        description="低频使用AKShare获取东财个股新闻、财联社快讯和东财全球资讯。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="https://akshare.akfamily.xyz",
        features=["个股新闻", "财联社快讯", "全球资讯"],
    ),

    DataSourceCode.CNINFO: DataSourceInfo(
        code=DataSourceCode.CNINFO,
        name="Cninfo Announcements",
        display_name="巨潮公告",
        provider="Cninfo via AKShare",
        description="巨潮公告全文入口，mootdx F10提供摘要补充。",
        supported_markets=["a_shares"],
        requires_api_key=False,
        is_free=True,
        official_website="https://www.cninfo.com.cn/",
        features=["公告全文", "公告摘要", "沪深北公告"],
    ),
    
    # yfinance
    DataSourceCode.YFINANCE: DataSourceInfo(
        code=DataSourceCode.YFINANCE,
        name="yfinance",
        display_name="yfinance (Yahoo Finance)",
        provider="Yahoo Finance",
        description="Yahoo Finance Python库，支持美股、港股等多个市场，完全免费",
        supported_markets=["us_stocks", "hk_stocks"],
        requires_api_key=False,
        is_free=True,
        official_website="https://finance.yahoo.com",
        documentation_url="https://pypi.org/project/yfinance/",
        features=["历史行情", "实时行情", "技术指标", "全球市场", "完全免费"],
    ),

    # Finnhub
    DataSourceCode.FINNHUB: DataSourceInfo(
        code=DataSourceCode.FINNHUB,
        name="Finnhub",
        display_name="Finnhub",
        provider="Finnhub",
        description="美股实时数据和新闻接口，提供高质量的市场数据",
        supported_markets=["us_stocks"],
        requires_api_key=True,
        is_free=True,  # 有免费版
        official_website="https://finnhub.io",
        documentation_url="https://finnhub.io/docs/api",
        features=["实时行情", "历史数据", "新闻资讯", "财务数据", "技术指标"],
    ),
    
    # Yahoo Finance
    DataSourceCode.YAHOO_FINANCE: DataSourceInfo(
        code=DataSourceCode.YAHOO_FINANCE,
        name="Yahoo Finance",
        display_name="Yahoo Finance",
        provider="Yahoo",
        description="全球股票数据接口，支持美股、港股等多个市场",
        supported_markets=["us_stocks", "hk_stocks"],
        requires_api_key=False,
        is_free=True,
        official_website="https://finance.yahoo.com",
        features=["历史行情", "实时行情", "全球市场", "完全免费"],
    ),
    
    # Alpha Vantage
    DataSourceCode.ALPHA_VANTAGE: DataSourceInfo(
        code=DataSourceCode.ALPHA_VANTAGE,
        name="Alpha Vantage",
        display_name="Alpha Vantage",
        provider="Alpha Vantage",
        description="美股技术分析数据接口，提供丰富的技术指标",
        supported_markets=["us_stocks"],
        requires_api_key=True,
        is_free=True,  # 有免费版
        official_website="https://www.alphavantage.co",
        documentation_url="https://www.alphavantage.co/documentation",
        features=["技术指标", "历史数据", "外汇数据", "加密货币"],
    ),
    
    # IEX Cloud
    DataSourceCode.IEX_CLOUD: DataSourceInfo(
        code=DataSourceCode.IEX_CLOUD,
        name="IEX Cloud",
        display_name="IEX Cloud",
        provider="IEX Cloud",
        description="美股实时数据接口，提供高质量的市场数据",
        supported_markets=["us_stocks"],
        requires_api_key=True,
        is_free=False,  # 需付费
        official_website="https://iexcloud.io",
        documentation_url="https://iexcloud.io/docs/api",
        features=["实时行情", "历史数据", "财务数据", "新闻资讯"],
    ),
    
    # Wind
    DataSourceCode.WIND: DataSourceInfo(
        code=DataSourceCode.WIND,
        name="Wind",
        display_name="Wind 万得",
        provider="Wind 万得",
        description="专业金融终端，提供全面的金融数据和分析工具",
        supported_markets=["a_shares", "hk_stocks", "us_stocks"],
        requires_api_key=True,
        is_free=False,  # 专业版需付费
        official_website="https://www.wind.com.cn",
        features=["专业数据", "全市场覆盖", "高质量数据", "专业分析"],
    ),
    
    # Choice
    DataSourceCode.CHOICE: DataSourceInfo(
        code=DataSourceCode.CHOICE,
        name="Choice",
        display_name="东方财富 Choice",
        provider="东方财富",
        description="专业金融数据终端，提供全面的A股数据",
        supported_markets=["a_shares"],
        requires_api_key=True,
        is_free=False,  # 专业版需付费
        official_website="http://choice.eastmoney.com",
        features=["专业数据", "A股专注", "高质量数据", "专业分析"],
    ),
    
    # Quandl
    DataSourceCode.QUANDL: DataSourceInfo(
        code=DataSourceCode.QUANDL,
        name="Quandl",
        display_name="Quandl",
        provider="Nasdaq",
        description="经济和金融数据平台，提供全球经济数据",
        supported_markets=["us_stocks"],
        requires_api_key=True,
        is_free=True,  # 有免费版
        official_website="https://www.quandl.com",
        documentation_url="https://docs.quandl.com",
        features=["经济数据", "金融数据", "全球覆盖"],
    ),
    
    # Local File
    DataSourceCode.LOCAL_FILE: DataSourceInfo(
        code=DataSourceCode.LOCAL_FILE,
        name="Local File",
        display_name="本地文件",
        provider="本地",
        description="从本地文件读取数据",
        supported_markets=["a_shares", "us_stocks", "hk_stocks"],
        requires_api_key=False,
        is_free=True,
        features=["离线可用", "自定义数据", "完全免费"],
    ),
    
    # Custom
    DataSourceCode.CUSTOM: DataSourceInfo(
        code=DataSourceCode.CUSTOM,
        name="Custom",
        display_name="自定义数据源",
        provider="自定义",
        description="自定义数据源接口",
        supported_markets=["a_shares", "us_stocks", "hk_stocks"],
        requires_api_key=False,
        is_free=True,
        features=["自定义接口", "灵活配置"],
    ),
}


# ==================== 辅助函数 ====================

def get_data_source_info(code: str) -> Optional[DataSourceInfo]:
    """
    获取数据源信息
    
    Args:
        code: 数据源编码
    
    Returns:
        数据源信息，如果不存在则返回 None
    """
    return DATA_SOURCE_REGISTRY.get(code)


def list_all_data_sources() -> List[DataSourceInfo]:
    """
    列出所有数据源
    
    Returns:
        所有数据源信息列表
    """
    return list(DATA_SOURCE_REGISTRY.values())


def list_data_sources_by_market(market: str) -> List[DataSourceInfo]:
    """
    列出支持指定市场的数据源
    
    Args:
        market: 市场类型（a_shares, us_stocks, hk_stocks, etc.）
    
    Returns:
        支持该市场的数据源列表
    """
    return [
        info for info in DATA_SOURCE_REGISTRY.values()
        if market in info.supported_markets
    ]


def list_free_data_sources() -> List[DataSourceInfo]:
    """
    列出所有免费数据源
    
    Returns:
        免费数据源列表
    """
    return [
        info for info in DATA_SOURCE_REGISTRY.values()
        if info.is_free
    ]


def is_data_source_supported(code: str) -> bool:
    """
    检查数据源是否支持
    
    Args:
        code: 数据源编码
    
    Returns:
        是否支持
    """
    return code in DATA_SOURCE_REGISTRY
