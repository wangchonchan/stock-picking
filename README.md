# Stock Picking System (股票自动选股系统)

这是一个基于 Python 和 Flask 构建的自动选股系统，支持港股和美股市场。

## 功能特点
- **多维度选股**：
  - Section 1: PB < 1 (破净股)
  - Section 2: RSI < 35 (超卖区间)
  - Section 3: RSI > 65 (超买区间)
- **自动存储**：每日选股结果自动以 JSON 格式存入 GitHub 仓库。
- **多市场支持**：支持切换港股 (HK) 和美股 (US)。
- **Hugging Face 部署**：专为 Hugging Face Spaces 优化。

## 部署说明 (Hugging Face)
1. 在 Hugging Face 创建一个新的 Space，选择 **Docker** 或 **Static SDK** (本项目使用 Flask，建议用 Docker 或直接运行 app.py)。
2. 在 Space 的 **Settings** -> **Variables and secrets** 中添加以下变量：
   - `GITHUB_TOKEN`: 您的 GitHub Personal Access Token (需要 repo 写入权限)。
3. 将本项目代码上传至 Space。

## 技术栈
- Backend: Python, Flask, yfinance, pandas
- Frontend: HTML5, Tailwind CSS, JavaScript
- Storage: GitHub API
