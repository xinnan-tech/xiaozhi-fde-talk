# 本地开发部署

不改源码、不调 CI，三件套跑通开发环境：

- **后端**：conda 建虚拟环境 + pip 装依赖 + `python main.py`
- **前端**：pnpm install + pnpm dev
- **语音识别**：单独起 FunASR Docker（按需；用豆包流式 API 可不开本地容器）

只是想试用产品，**直接看 [README.md 走 Docker 部署](../README.md)** 更快。

---

## 1. 后端

```bash
cd backend
conda create -n xiaozhi-fde-talk python=3.12 -y
conda activate xiaozhi-fde-talk
pip install -r requirements.txt
mkdir -p data
cp .env.example data/.env
python main.py
```

国内用户可在 `pip install` 后追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 走清华镜像。

启动后，API 文档在 `http://localhost:8000/docs` 查看。

---

## 2. 前端

```bash
cd frontend
pnpm install
pnpm dev
```

---

## 3. 语音识别（按需）

### 3.1 推荐本地免费 FunASR

```bash
docker compose up -d funasr
docker compose logs -f funasr
```

第一次会下载几个 G 的模型，等日志显示模型就绪再回系统配置页面。容器里监听 10095 端口，映射到宿主机 10096。

### 3.2 不想跑 Docker？

直接用 [豆包流式 API](asr-config.md)，免本地推理、免模型等待。

---

## 4. 浏览器访问

打开 [https://localhost:8848](https://localhost:8848)。

浏览器会弹「连接不安全」——别紧张。这是开发用的演示证书，点「高级 → 继续前往 localhost」放行。

进系统后下一步见 [用户使用教程](user-tutorial.md)（注册 → 配置 → 跑访谈 → 导出报告）。