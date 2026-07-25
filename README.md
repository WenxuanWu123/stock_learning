# A股投资互动教学站 · 使用说明（站长版）

写给站长的傻瓜手册。你**只需要编辑 `content/` 和 `levels/` 下的 Markdown / JSON**，
其他一切都是代码，不用碰。

## 一、起站 / 关站

```bash
./run.sh        # 一条命令：自动建环境、装依赖、建库、起站
```

然后浏览器打开 **http://127.0.0.1:8000** 。按 `Ctrl+C` 关站。
重复执行 `./run.sh` 不会重复装东西，放心用。

## 二、改了内容之后

```bash
./rebuild.sh    # 删库重建：重新注入全部数字、重新渲染课文
```

网页上的课文和题目全部来自数据库，数据库全部来自 `content/` + `levels/` + `data/`，
所以**改完文件跑一次 `./rebuild.sh` 就生效**。

## 三、怎么加新课文和题目

在对应模块下新建一个文件夹（编号-英文名）：

```
content/concepts/02-what-is-kline/
  lesson.md     # 课文
  quiz.json     # 10 道题
```

`lesson.md` 开头必须有 front-matter（照抄改字即可）：

```markdown
---
title: K线是什么
order: 2
sources:
  - 《日本蜡烛图技术》
  - 上交所投资者教育材料
---

# 正文用 Markdown 写……
```

- `title`：章节标题；`order`：排序号；`sources`：参考来源（**必填，至少一条**）。
- 正文里**一切具体数字都不许手写**，用 `{{calc:...}}` 占位符（语法见 项目.md
  「calc 占位符语法」一节），建站时会自动替换成脚本从真实行情算出的数字。

`quiz.json` 格式：

```json
{"questions": [
  {"q": "题干", "options": ["A","B","C","D"], "answer": 0, "explanation": "答错时显示的解析"}
]}
```

`answer` 是正确选项的下标（0=第一个）。题干、选项、解析里都可以用 `{{calc:...}}`。

## 四、怎么加 B 型关卡

在 `levels/` 下新建 `NN-英文名.json`：

```json
{
  "title": "关卡标题",
  "symbol": "sh000001",
  "decision_date": "2025-04-07",
  "reveal_days": 20,
  "context_days": 120,
  "question": "场景描述（可用 {{calc:...}}）",
  "options": [
    {"key": "A", "text": "选项文字", "score": 100, "feedback": "选这个会看到的解析"}
  ]
}
```

- `symbol`：sh000001 上证指数 / sh000300 沪深300 / sh000905 中证500
- `decision_date`：决策日（K 线图画到这里停住）
- `reveal_days`：用户决策后揭示后面多少天的走势
- `score` 0~100，`feedback` 里也能用 `{{calc:...}}`

## 五、目录结构

```
run.sh / rebuild.sh      起站 / 重建数据库
requirements.txt         Python 依赖（锁版本）
.venv/                   Python 环境（不进 git）
stock_learning.db        SQLite 数据库（不进 git，rebuild.sh 重建）
app/                     后端代码（不用碰）
static/                  前端页面（不用碰）
data/                    冻结行情 CSV（随 git 分发，别改）
content/<模块>/<章节>/   课文 + 题目 ← 你只编辑这里
levels/                  B 型关卡  ← 和这里
private/                 隐私文件（交割单等，gitignore，不会进仓库）
项目.md                  项目宪法（含 calc 占位符语法）
```

## 六、常见问题

- **页面没变化？** 改完内容要跑 `./rebuild.sh`，再刷新浏览器。
- **rebuild 报错？** 多半是 JSON 少逗号、front-matter 缺字段，或 calc 占位符写错，
  报错信息会指出是哪个文件、哪个占位符。
- **答题记录会丢吗？** `./rebuild.sh` 会连答题记录一起重建（清空）。
  正常学习不要频繁 rebuild，只在改内容后用。
