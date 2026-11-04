# 食刻 · FoodMate

让每一餐，都有科学依据。FoodMate 是一个中文 Streamlit MVP，演示食物图片识别、营养估算、菜谱推荐和一餐饮食规划。

> 免责声明：本项目提供一般饮食信息，不替代医生或注册营养师建议。份量和营养均为估算。`data/` 中是项目自制的近似演示数据，不是完整的营养数据库。

## 功能

- **食物识别：** 演示模式使用明确标注的预设样例；真实 AI 模式可上传 JPG、PNG、WebP 或 HEIC 照片，应用会校正手机照片方向并压缩为 JPEG 后再使用 DeepSeek `deepseek-flash` 识别可见食物。用户可增删食材、修改名称和重量。
- **营养计算：** Python 按本地每 100 克营养数据计算热量、蛋白质、脂肪和碳水。未匹配食材会标注为缺失，不会把缺失值伪装成完整总量。
- **菜谱推荐：** 根据确认食材匹配项目自制的中式家常菜；真实 AI 模式在本地匹配不足时可生成候选，候选只能引用本地食材目录，营养由程序重算。
- **饮食规划：** 检查热量范围、菜品数量、必选/排除食材、已知过敏原及总烹饪时间。多道菜的耗时按各菜分钟数相加。软性饮食偏好用于排序。
- **隐私：** 图片只在当前会话处理，不写入项目文件。真实 AI 模式会把图片发送给 DeepSeek；上传前请阅读服务商政策并避免提交敏感图片。应用不提供账号、长期记录或跨设备同步。

## 本地运行

需要 Python 3.10 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

默认打开的是**演示模式**，不需要 API 密钥。要使用真实 AI 模式，可在 PowerShell 当前会话中设置：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
$env:DEEPSEEK_MODEL = "deepseek-flash"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
streamlit run app.py
```

也可以在本机创建 `.streamlit/secrets.toml`：

```toml
DEEPSEEK_API_KEY = "你的密钥"
DEEPSEEK_MODEL = "deepseek-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
```

密钥文件已加入 `.gitignore`，不要把真实密钥贴到聊天、README 或 Git 提交中。应用只在用户主动点击识别/生成按钮时调用模型；模型账户的余额和超额计费由服务商控制，请在服务商侧设置用量限制。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖营养计算、未知数据标记、份量变化、规划硬约束、过敏原排除及不可行方案。

## 部署

- [用户使用说明](docs/user-guide.md)
- [部署与迁移说明](docs/deployment.md)

Community Cloud 部署时选择 GitHub 仓库、`main` 分支及 `app.py`，再在应用 Secrets 中配置 DeepSeek 密钥。若只演示预设数据，不配置密钥也可运行。

## 项目结构

```text
app.py                 Streamlit 页面与交互
foodmate/              目录加载、模型调用、营养计算、约束规划
data/                  项目自制食物与菜谱演示数据
assets/                自制演示插画
tests/                 计算与规划测试
docs/                  用户与部署说明
```

## 技术说明与数据边界

AI 负责识别或生成候选，Python 负责营养计算和硬约束验证。模型输出可能错误，必须人工核对。当前食物数据规模有限，未知食材不纳入已知营养小计，并会在页面提示；不得将本演示数据用于医疗或精确营养管理。

本仓库不打包第三方菜谱或照片。菜谱步骤和矢量示例插画由项目自制；食物数值是用于演示计算的近似值。后续扩充数据前，需检查来源许可并保留归属信息。

## License

MIT License，详见 [LICENSE](LICENSE)。

