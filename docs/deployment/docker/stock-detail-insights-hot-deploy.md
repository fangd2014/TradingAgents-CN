# 股票详情深度数据热部署

本功能涉及 backend 和 frontend 镜像。热部署时必须保留 MongoDB image 和 volume，不要删除 `tradingagents-mongodb` 容器数据卷。

推荐命令：

```bash
docker compose build backend frontend
docker compose up -d backend frontend
docker compose ps
```

验证：

```bash
curl -f http://localhost:8000/api/health
curl -f http://localhost:3000/health
```

页面验证：

- 打开 `http://localhost:3000/stocks/688049`
- 确认右侧“快捷操作”存在 `详细财报`、`技术因子`、`神奇九转`
- 点击三个按钮，确认页面滚动和页签切换正常
