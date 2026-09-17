# Weekly Web Research Agent

本地网页设计调研助手：你下任务，它去网上找真实网站、截图、分析视觉和交互，再把案例存进**你自己的**资料库。

首页可以浏览风格分类、打开案例、复制复刻提示词。界面中英双语。

**这个仓库不提供任何 API Key，也不连接作者的数据库。** 你要用自己的 AI、自己的搜索、自己的 Supabase。纯本地存储以后再支持。

---

## 你需要准备什么

1. **Python 3.10+**
2. **AI API**（兼容 OpenAI 接口即可）  
   例如 DeepSeek、OpenAI。看网站截图时，模型最好支持图片（vision）。
3. **搜索 API**：[Tavily](https://tavily.com) 的 Key
4. **你自己的 [Supabase](https://supabase.com) 项目**（免费档即可）  
   案例会写进你项目里的 `research_cases` 表。别人看不到，作者也看不到。

费用由你自己的账号承担。本程序只在你这台电脑上跑。

---

## 安装

在项目目录里：

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

---

## 填写你的配置

复制一份环境变量文件，**只改你电脑上的这一份**：

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

用记事本打开 `.env`，填这几项：

| 变量 | 填什么 |
| --- | --- |
| `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` | 你的 AI Key（二选一即可） |
| `OPENAI_BASE_URL` | 接口地址，例如 `https://api.deepseek.com` 或 `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 模型名，例如 `deepseek-chat` 或 `gpt-4o` |
| `TAVILY_API_KEY` | 你的 Tavily Key |
| `SUPABASE_URL` | 你的项目 URL（Settings → API） |
| `SUPABASE_KEY` | 你的 **anon public** key（同一页） |

`.env` 已被 git 忽略。不要把真实 Key 贴到 README、Issue、截图或聊天里。

### 建你的数据表

1. 打开你的 Supabase 项目
2. Database → Extensions，启用 **vector**
3. SQL Editor 里粘贴并运行 [`sql/setup.sql`](sql/setup.sql)

这会创建 `research_cases` 表和语义检索函数。脚本里的权限适合**个人自用**（这台电脑用 anon key 读写）。不要把这个 Key 发给别人。

---

## 怎么用

每次先激活虚拟环境，再启动资料库页面：

```bash
python -m library
```

浏览器打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)

- **首页上方输入框**：提交调研任务（例如「找三个极简风格网站」或「研究 https://某个站点」）。提交会启动 Agent。和网站 / 风格调研无关的任务会被拒绝。
- **Search / Filter**：只搜索、筛选**已经存进库里的**案例，不会启动调研。
- 点某个风格进入风格页，再点案例看分析和复刻提示词。
- 任务跑着时可以继续逛库；需要停下来就点 Cancel。

也可以不用网页，直接在终端跑一次：

```bash
python main.py "找两个粗野主义风格的真实网站并保存"
```

截图会保存在本机 `screenshots/`，案例正文在你的 Supabase 里。首页分类列表来自本地 `data/library_index.json`（由案例自动生成，丢了可以重建）。这些本地文件都不会进 Git。

---

## 数据在哪、谁看得到

| 东西 | 存在哪 |
| --- | --- |
| 案例卡片 | **你的** Supabase `research_cases` |
| 截图 | 你这台电脑的 `screenshots/` |
| 首页分类索引 | 你这台电脑的 `data/` |

换一台电脑 = 换一份本地截图和索引；库里的文字案例仍在你的 Supabase。

作者不会收到你的 Key，也不会收到你存的网站。

---

## 以后

纯本地存储（不强制 Supabase）还没做。现在必须自备一个 Supabase 项目。

---

## 常见问题

**填了 Key 还是报缺 Key**  
确认文件名就是项目根目录的 `.env`，并且已激活 `.venv` 后再启动。

**截图分析失败**  
换一个支持看图的模型，或检查该模型的 Base URL 是否正确。

**首页是空的**  
新库本来就是空的。先提交一个调研任务，等状态变成 Completed，再看对应风格分类。
