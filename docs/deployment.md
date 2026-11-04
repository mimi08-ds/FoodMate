# 部署与迁移说明

## Streamlit Community Cloud

1. 将项目推送到 GitHub，并确认根目录有 `app.py` 和 `requirements.txt`。
2. 登录 Streamlit Community Cloud，创建应用，选择仓库、`main` 分支和 `app.py`。
3. 在应用的 Secrets 设置中填入（仅在需要真实 AI 时）：

   ```toml
   DEEPSEEK_API_KEY = "由你在 DeepSeek 账户中管理的密钥"
   DEEPSEEK_MODEL = "deepseek-flash"
   DEEPSEEK_BASE_URL = "https://api.deepseek.com"
   ```

4. 部署后先走通演示模式，再用一张非敏感图片验证真实 API。检查失败提示、日志和模型服务网络连通性。

不要把真实密钥提交到 GitHub。Streamlit 官方文档说明可在应用设置中保存 Secrets，且不应将 `secrets.toml` 提交到仓库：[Secrets 管理](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)。

## Linux 云服务器（迁移路径）

当前未开通或验证阿里云/腾讯云实例。项目不依赖 Community Cloud 专有运行接口；部署前仍需检查目标系统、Python、外部模型 API 连通性和安全组配置。

```bash
sudo apt update
sudo apt install -y python3 python3-venv
git clone https://github.com/mimi08-ds/FoodMate.git
cd FoodMate
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export DEEPSEEK_API_KEY='在服务器安全配置中注入，不要写入仓库'
export DEEPSEEK_MODEL='deepseek-flash'
export DEEPSEEK_BASE_URL='https://api.deepseek.com'
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

生产环境应使用服务管理器（如 systemd）和 HTTPS 反向代理，不要把 `8501` 端口直接暴露给公网。将密钥写入服务器 Secret/环境配置，限制文件权限；日志中不得输出密钥或上传图片。对外开放前还需配置访问控制、TLS、资源限制和备份策略。

## Python 与依赖

- Python 3.10+
- 依赖由 `requirements.txt` 管理
- 单张图片上传限制为 100 MB；上传后会在内存中校正方向并压缩，应用不把图片写入磁盘。手机网络较慢时，优先选择较小的图片可缩短等待时间
- 业务状态保存在 Streamlit 当前会话，不使用用户数据库

国内云实际实例和费用尚未确定；部署到具体阿里云或腾讯云产品时，需按实际操作系统、区域网络、域名和备案要求补充配置。

