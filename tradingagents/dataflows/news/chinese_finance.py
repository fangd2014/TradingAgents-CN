#!/usr/bin/env python3
"""
中国财经数据聚合工具
由于微博API申请困难且功能受限，采用多源数据聚合的方式
"""

import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import re
from bs4 import BeautifulSoup


class ChineseFinanceDataAggregator:
    """中国财经数据聚合器"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_stock_sentiment_summary(self, ticker: str, days: int = 7) -> Dict:
        """
        获取股票情绪分析汇总
        整合多个可获取的中国财经数据源
        """
        try:
            # 1. 获取财经新闻情绪
            news_sentiment = self._get_finance_news_sentiment(ticker, days)
            
            # 2. 获取投资社区讨论情绪
            forum_sentiment = self._get_stock_forum_sentiment(ticker, days)
            
            # 3. 获取财经媒体报道
            media_sentiment = self._get_media_coverage_sentiment(ticker, days)
            
            # 4. 综合分析
            overall_sentiment = self._calculate_overall_sentiment(
                news_sentiment, forum_sentiment, media_sentiment
            )
            
            return {
                'ticker': ticker,
                'analysis_period': f'{days} days',
                'overall_sentiment': overall_sentiment,
                'news_sentiment': news_sentiment,
                'forum_sentiment': forum_sentiment,
                'media_sentiment': media_sentiment,
                'summary': self._generate_sentiment_summary(overall_sentiment),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'ticker': ticker,
                'error': f'数据获取失败: {str(e)}',
                'fallback_message': '由于中国社交媒体API限制，建议使用财经新闻和基本面分析作为主要参考',
                'timestamp': datetime.now().isoformat()
            }
    
    def _get_finance_news_sentiment(self, ticker: str, days: int) -> Dict:
        """获取财经新闻情绪分析"""
        try:
            # 搜索相关新闻标题和内容
            company_name = self._get_company_chinese_name(ticker)
            search_terms = [ticker, company_name] if company_name else [ticker]
            
            news_items = []
            seen_news = set()
            for term in search_terms:
                # 这里可以集成多个新闻源
                items = self._search_finance_news(term, days)
                for item in items:
                    dedupe_key = item.get('url') or item.get('title')
                    if dedupe_key and dedupe_key in seen_news:
                        continue
                    if dedupe_key:
                        seen_news.add(dedupe_key)
                    news_items.append(item)
            
            # 简单的情绪分析
            positive_count = 0
            negative_count = 0
            neutral_count = 0
            
            for item in news_items:
                sentiment = self._analyze_text_sentiment(item.get('title', '') + ' ' + item.get('content', ''))
                if sentiment > 0.1:
                    positive_count += 1
                elif sentiment < -0.1:
                    negative_count += 1
                else:
                    neutral_count += 1
            
            total = len(news_items)
            if total == 0:
                return {'sentiment_score': 0, 'confidence': 0, 'news_count': 0}
            
            sentiment_score = (positive_count - negative_count) / total
            
            return {
                'sentiment_score': sentiment_score,
                'positive_ratio': positive_count / total,
                'negative_ratio': negative_count / total,
                'neutral_ratio': neutral_count / total,
                'news_count': total,
                'news_items': news_items[:10],
                'confidence': min(total / 10, 1.0)  # 新闻数量越多，置信度越高
            }
            
        except Exception as e:
            return {'error': str(e), 'sentiment_score': 0, 'confidence': 0}
    
    def _get_stock_forum_sentiment(self, ticker: str, days: int) -> Dict:
        """获取股票论坛/投资社区讨论情绪。"""
        source_order = ["同花顺", "东方财富", "雪球"]
        source_stats = {}
        all_items = []

        for source in source_order:
            try:
                items = self._fetch_forum_source(source, ticker, days)
                source_stats[source] = {
                    'count': len(items),
                    'status': 'success' if items else 'empty',
                }
                all_items.extend(items)
            except Exception as e:
                source_stats[source] = {
                    'count': 0,
                    'status': 'failed',
                    'error': str(e)[:120],
                }

        if not all_items:
            return {
                'sentiment_score': 0,
                'discussion_count': 0,
                'hot_topics': [],
                'source_stats': source_stats,
                'note': '同花顺、东方财富、雪球均未获取到可用讨论数据',
                'confidence': 0,
            }

        sentiment_scores = []
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        hot_topics = []

        for item in all_items:
            text = f"{item.get('title', '')} {item.get('content', '')}"
            score = self._analyze_text_sentiment(text)
            sentiment_scores.append(score)

            if score > 0.1:
                positive_count += 1
            elif score < -0.1:
                negative_count += 1
            else:
                neutral_count += 1

            title = item.get('title') or item.get('content', '')[:40]
            if title:
                hot_topics.append({
                    'source': item.get('source', '未知'),
                    'title': title[:80],
                    'sentiment_score': score,
                    'url': item.get('url', ''),
                })

        total = len(all_items)
        sentiment_score = sum(sentiment_scores) / total if total else 0

        return {
            'sentiment_score': sentiment_score,
            'positive_ratio': positive_count / total,
            'negative_ratio': negative_count / total,
            'neutral_ratio': neutral_count / total,
            'discussion_count': total,
            'hot_topics': hot_topics[:5],
            'source_stats': source_stats,
            'confidence': min(total / 15, 1.0),
        }

    def _fetch_forum_source(self, source: str, ticker: str, days: int) -> List[Dict[str, Any]]:
        """按来源获取投资社区内容。"""
        if source == "同花顺":
            return self._fetch_10jqka_discussions(ticker, days)
        if source == "东方财富":
            return self._fetch_eastmoney_guba_discussions(ticker, days)
        if source == "雪球":
            return self._fetch_xueqiu_discussions(ticker, days)
        raise ValueError(f"不支持的社媒情绪来源: {source}")

    def _fetch_10jqka_discussions(self, ticker: str, days: int) -> List[Dict[str, Any]]:
        """从同花顺搜索页尽力提取个股讨论/资讯信号。"""
        clean_ticker = self._normalize_cn_stock_code(ticker)
        url = "https://search.10jqka.com.cn/search"
        response = self.session.get(url, params={'w': clean_ticker}, timeout=8)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for link in soup.find_all('a', href=True):
            title = self._clean_text(link.get_text(" ", strip=True))
            href = link.get('href', '')
            if not title or len(title) < 6:
                continue
            if clean_ticker not in title and clean_ticker not in href:
                continue
            items.append({
                'source': '同花顺',
                'title': title,
                'content': '',
                'url': href,
                'publish_time': datetime.now().isoformat(),
            })
            if len(items) >= 20:
                break
        return items

    def _fetch_eastmoney_guba_discussions(self, ticker: str, days: int) -> List[Dict[str, Any]]:
        """从东方财富股吧接口尽力提取讨论信号。"""
        clean_ticker = self._normalize_cn_stock_code(ticker)
        url = "https://guba.eastmoney.com/interface/GetData.aspx"
        params = {
            'type': '1',
            'code': clean_ticker,
            'ps': '20',
            'p': '1',
            'sort': '1',
        }
        response = self.session.get(url, params=params, timeout=8)
        response.raise_for_status()
        self._ensure_json_response(response, "东方财富股吧")
        return self._parse_eastmoney_guba_payload(response.text, clean_ticker)

    def _fetch_xueqiu_discussions(self, ticker: str, days: int) -> List[Dict[str, Any]]:
        """从雪球公开搜索接口尽力提取讨论信号。"""
        clean_ticker = self._normalize_cn_stock_code(ticker)
        symbol = self._to_xueqiu_symbol(clean_ticker)

        # 先访问首页拿基础 Cookie；雪球未授权时可能仍会拒绝，调用方会记录失败原因。
        try:
            self.session.get("https://xueqiu.com/", timeout=8)
        except Exception:
            pass

        url = "https://xueqiu.com/query/v1/search/status.json"
        response = self.session.get(url, params={'q': symbol, 'count': 20}, timeout=8)
        response.raise_for_status()
        self._ensure_json_response(response, "雪球")
        payload = response.json()

        statuses = payload.get('list') or payload.get('statuses') or []
        items = []
        for status in statuses:
            title = self._clean_text(status.get('title') or status.get('description') or '')
            content = self._clean_text(status.get('text') or status.get('description') or '')
            if not title and not content:
                continue
            status_id = status.get('id') or status.get('target')
            items.append({
                'source': '雪球',
                'title': title or content[:60],
                'content': content,
                'url': f"https://xueqiu.com{status_id}" if str(status_id).startswith('/') else '',
                'publish_time': datetime.now().isoformat(),
            })
        return items

    def _parse_eastmoney_guba_payload(self, text: str, ticker: str) -> List[Dict[str, Any]]:
        """解析东方财富股吧接口的多种返回结构。"""
        payload = json.loads(text)
        candidates = []

        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            for key in ('re', 'data', 'list', 'result'):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
                if isinstance(value, dict):
                    for nested_key in ('list', 'items', 'posts'):
                        nested_value = value.get(nested_key)
                        if isinstance(nested_value, list):
                            candidates = nested_value
                            break
                if candidates:
                    break

        items = []
        for raw in candidates:
            if not isinstance(raw, dict):
                continue
            title = self._clean_text(
                raw.get('post_title')
                or raw.get('title')
                or raw.get('post_content')
                or raw.get('content')
                or ''
            )
            content = self._clean_text(raw.get('post_content') or raw.get('content') or '')
            if not title and not content:
                continue
            post_id = raw.get('post_id') or raw.get('id')
            items.append({
                'source': '东方财富',
                'title': title or content[:60],
                'content': content,
                'url': f"https://guba.eastmoney.com/news,{ticker},{post_id}.html" if post_id else '',
                'publish_time': raw.get('post_publish_time') or raw.get('publish_time') or datetime.now().isoformat(),
            })
        return items

    def _normalize_cn_stock_code(self, ticker: str) -> str:
        """标准化 A 股代码为 6 位数字。"""
        code = str(ticker).upper().strip()
        code = re.sub(r'\.(SH|SZ|SS|XSHE|XSHG)$', '', code)
        code = re.sub(r'^(SH|SZ)', '', code)
        digits = re.sub(r'\D', '', code)
        return digits.zfill(6) if digits else code

    def _to_xueqiu_symbol(self, ticker: str) -> str:
        """转换为雪球常用代码格式。"""
        if ticker.startswith(('60', '68', '90')):
            return f"SH{ticker}"
        return f"SZ{ticker}"

    def _clean_text(self, text: str) -> str:
        """清洗 HTML 和多余空白。"""
        if not text:
            return ''
        text = BeautifulSoup(str(text), 'html.parser').get_text(' ', strip=True)
        return re.sub(r'\s+', ' ', text).strip()

    def _ensure_json_response(self, response: requests.Response, source: str) -> None:
        """在解析前识别空响应、HTML/WAF 页面，避免暴露 JSONDecodeError。"""
        text = (response.text or '').strip()
        content_type = (response.headers.get('content-type') or '').lower()
        if not text:
            raise ValueError(f"{source}返回空响应，可能接口变更或反爬限制")
        if 'aliyun_waf' in text.lower() or '_waf_' in text.lower():
            raise ValueError(f"{source}返回WAF拦截页面，需要有效登录态或接口已受限")
        if 'json' in content_type or text.startswith(('{', '[')):
            return
        if text.startswith(('<!doctype', '<html', '<textarea')):
            raise ValueError(f"{source}返回HTML页面而非JSON，可能接口变更或反爬限制")
        raise ValueError(f"{source}返回非JSON响应: content-type={content_type or 'unknown'}")
    
    def _get_media_coverage_sentiment(self, ticker: str, days: int) -> Dict:
        """获取媒体报道情绪"""
        try:
            # 可以集成RSS源或公开的财经API
            coverage_items = self._get_media_coverage(ticker, days)
            
            if not coverage_items:
                return {'sentiment_score': 0, 'coverage_count': 0, 'confidence': 0}
            
            # 分析媒体报道的情绪倾向
            sentiment_scores = []
            for item in coverage_items:
                score = self._analyze_text_sentiment(item.get('title', '') + ' ' + item.get('summary', ''))
                sentiment_scores.append(score)
            
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
            
            return {
                'sentiment_score': avg_sentiment,
                'coverage_count': len(coverage_items),
                'confidence': min(len(coverage_items) / 5, 1.0)
            }
            
        except Exception as e:
            return {'error': str(e), 'sentiment_score': 0, 'confidence': 0}
    
    def _search_finance_news(self, search_term: str, days: int) -> List[Dict]:
        """搜索真实财经新闻，A股优先使用 AKShare 东方财富新闻。"""
        clean_ticker = self._normalize_cn_stock_code(search_term)
        if not re.fullmatch(r'\d{6}', clean_ticker):
            return []

        try:
            from tradingagents.dataflows.providers.china.akshare import AKShareProvider

            provider = AKShareProvider()
            news_df = provider.get_stock_news_sync(symbol=clean_ticker, limit=20)
            if news_df is None or news_df.empty:
                return []

            cutoff = datetime.now() - timedelta(days=days)
            items = []
            for _, row in news_df.iterrows():
                title = self._clean_text(row.get('新闻标题', '') or row.get('标题', ''))
                if not title:
                    continue
                publish_time = row.get('发布时间', '') or row.get('时间', '')
                if not self._is_recent_news(publish_time, cutoff):
                    continue
                items.append({
                    'title': title,
                    'content': self._clean_text(row.get('新闻内容', '') or row.get('内容', '') or row.get('摘要', '')),
                    'source': row.get('文章来源', '') or row.get('来源', '') or '东方财富新闻',
                    'publish_time': str(publish_time) if publish_time is not None else '',
                    'url': row.get('新闻链接', '') or row.get('链接', ''),
                })
                if len(items) >= 20:
                    break
            return items
        except Exception:
            return []

    def _is_recent_news(self, publish_time: Any, cutoff: datetime) -> bool:
        """尽力按发布时间过滤新闻；无法解析时保留，避免误杀数据源返回。"""
        if not publish_time:
            return True
        if isinstance(publish_time, datetime):
            return publish_time >= cutoff
        text = str(publish_time).strip()
        if not text:
            return True
        parse_candidates = [text, text[:19], text[:10]]
        for candidate in parse_candidates:
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d'):
                try:
                    return datetime.strptime(candidate, fmt) >= cutoff
                except ValueError:
                    continue
        return True
    
    def _get_media_coverage(self, ticker: str, days: int) -> List[Dict]:
        """获取媒体报道 (示例实现)"""
        # 可以集成Google News API或其他新闻聚合服务
        return []
    
    def _analyze_text_sentiment(self, text: str) -> float:
        """简单的中文文本情绪分析"""
        if not text:
            return 0
        
        # 简单的关键词情绪分析
        positive_words = ['上涨', '增长', '利好', '看好', '买入', '推荐', '强势', '突破', '创新高']
        negative_words = ['下跌', '下降', '利空', '看空', '卖出', '风险', '跌破', '创新低', '亏损']
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        if positive_count + negative_count == 0:
            return 0
        
        return (positive_count - negative_count) / (positive_count + negative_count)
    
    def _get_company_chinese_name(self, ticker: str) -> Optional[str]:
        """获取公司中文名称"""
        # 简单的映射表，实际可以从数据库或API获取
        name_mapping = {
            'AAPL': '苹果',
            'TSLA': '特斯拉',
            'NVDA': '英伟达',
            'MSFT': '微软',
            'GOOGL': '谷歌',
            'AMZN': '亚马逊'
        }
        return name_mapping.get(ticker.upper())
    
    def _calculate_overall_sentiment(self, news_sentiment: Dict, forum_sentiment: Dict, media_sentiment: Dict) -> Dict:
        """计算综合情绪分析"""
        # 根据各数据源的置信度加权计算
        news_weight = news_sentiment.get('confidence', 0)
        forum_weight = forum_sentiment.get('confidence', 0)
        media_weight = media_sentiment.get('confidence', 0)
        
        total_weight = news_weight + forum_weight + media_weight
        
        if total_weight == 0:
            return {'sentiment_score': 0, 'confidence': 0, 'level': 'neutral'}
        
        weighted_sentiment = (
            news_sentiment.get('sentiment_score', 0) * news_weight +
            forum_sentiment.get('sentiment_score', 0) * forum_weight +
            media_sentiment.get('sentiment_score', 0) * media_weight
        ) / total_weight
        
        # 确定情绪等级
        if weighted_sentiment > 0.3:
            level = 'very_positive'
        elif weighted_sentiment > 0.1:
            level = 'positive'
        elif weighted_sentiment > -0.1:
            level = 'neutral'
        elif weighted_sentiment > -0.3:
            level = 'negative'
        else:
            level = 'very_negative'
        
        return {
            'sentiment_score': weighted_sentiment,
            'confidence': total_weight / 3,  # 平均置信度
            'level': level
        }
    
    def _generate_sentiment_summary(self, overall_sentiment: Dict) -> str:
        """生成情绪分析摘要"""
        level = overall_sentiment.get('level', 'neutral')
        score = overall_sentiment.get('sentiment_score', 0)
        confidence = overall_sentiment.get('confidence', 0)
        
        level_descriptions = {
            'very_positive': '非常积极',
            'positive': '积极',
            'neutral': '中性',
            'negative': '消极',
            'very_negative': '非常消极'
        }
        
        description = level_descriptions.get(level, '中性')
        confidence_level = '高' if confidence > 0.7 else '中' if confidence > 0.3 else '低'
        
        return f"市场情绪: {description} (评分: {score:.2f}, 置信度: {confidence_level})"


def get_chinese_social_sentiment(ticker: str, curr_date: str) -> str:
    """
    获取中国社交媒体情绪分析的主要接口函数
    """
    aggregator = ChineseFinanceDataAggregator()
    
    try:
        # 获取情绪分析数据
        sentiment_data = aggregator.get_stock_sentiment_summary(ticker, days=7)
        
        # 格式化输出
        if 'error' in sentiment_data:
            return f"""
中国市场情绪分析报告 - {ticker}
分析日期: {curr_date}

⚠️ 数据获取限制说明:
{sentiment_data.get('fallback_message', '数据获取遇到技术限制')}

建议:
1. 重点关注财经新闻和基本面分析
2. 参考官方财报和业绩指导
3. 关注行业政策和监管动态
4. 考虑国际市场情绪对中概股的影响

注: 由于中国社交媒体平台API限制，当前主要依赖公开财经数据源进行分析。
"""
        
        overall = sentiment_data.get('overall_sentiment', {})
        news = sentiment_data.get('news_sentiment', {})
        forum = sentiment_data.get('forum_sentiment', {})
        source_stats = forum.get('source_stats', {})
        source_lines = []
        for source_name in ["同花顺", "东方财富", "雪球"]:
            stats = source_stats.get(source_name, {})
            count = stats.get('count', 0)
            status = stats.get('status', 'not_attempted')
            error = stats.get('error')
            line = f"- {source_name}: {count}条 ({status})"
            if error:
                line += f" - {error}"
            source_lines.append(line)

        news_count = news.get('news_count', 0)
        discussion_count = forum.get('discussion_count', 0)
        failed_sources = [
            source_name
            for source_name, stats in source_stats.items()
            if stats.get('status') == 'failed'
        ]
        if discussion_count == 0 and failed_sources and news_count:
            availability_note = (
                "社区讨论源异常，不代表真实市场情绪真空；"
                "已使用财经新闻情绪作为补充参考。"
            )
        elif discussion_count == 0:
            availability_note = "未获取到可用投资社区讨论样本，情绪判断置信度较低。"
        else:
            availability_note = "投资社区样本已纳入情绪评分。"

        hot_topics = forum.get('hot_topics', [])
        topic_lines = []
        for topic in hot_topics[:5]:
            topic_lines.append(
                f"- [{topic.get('source', '未知')}] {topic.get('title', '')} "
                f"(情绪: {topic.get('sentiment_score', 0):.2f})"
            )
        if not topic_lines:
            topic_lines.append("- 暂无可用热门讨论样本")
        
        return f"""
中国市场情绪分析报告 - {ticker}
分析日期: {curr_date}
分析周期: {sentiment_data.get('analysis_period', '7天')}

📊 综合情绪评估:
{sentiment_data.get('summary', '数据不足')}

📰 财经新闻情绪:
- 情绪评分: {news.get('sentiment_score', 0):.2f}
- 正面新闻比例: {news.get('positive_ratio', 0):.1%}
- 负面新闻比例: {news.get('negative_ratio', 0):.1%}
- 新闻数量: {news.get('news_count', 0)}条

💬 投资社区情绪:
- 情绪评分: {forum.get('sentiment_score', 0):.2f}
- 正面讨论比例: {forum.get('positive_ratio', 0):.1%}
- 负面讨论比例: {forum.get('negative_ratio', 0):.1%}
- 讨论样本数: {forum.get('discussion_count', 0)}条
- 可用性说明: {availability_note}

数据源尝试:
{chr(10).join(source_lines)}

热门讨论样本:
{chr(10).join(topic_lines)}

💡 投资建议:
基于当前可获取的中国市场数据，建议投资者:
1. 密切关注官方财经媒体报道
2. 结合同花顺、东方财富、雪球讨论热度观察散户情绪变化
3. 重视基本面分析和财务数据
4. 考虑政策环境对股价的影响

⚠️ 数据说明:
同花顺、东方财富、雪球公开页面可能受反爬、登录态或接口变更影响；失败源会在“数据源尝试”中标注。
建议结合新闻、基本面和技术面进行综合判断。

生成时间: {sentiment_data.get('timestamp', datetime.now().isoformat())}
"""
        
    except Exception as e:
        return f"""
中国市场情绪分析 - {ticker}
分析日期: {curr_date}

❌ 分析失败: {str(e)}

💡 替代建议:
1. 查看财经新闻网站的相关报道
2. 关注雪球、东方财富等投资社区讨论
3. 参考专业机构的研究报告
4. 重点分析基本面和技术面数据

注: 中国社交媒体数据获取存在技术限制，建议以基本面分析为主。
"""
