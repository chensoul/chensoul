# Linkding 书签 API 用法

- 站点：<https://linkding.chensoul.cc/>
- 认证：API Token（后台 设置 → 集成 创建）
- 请求头：`Authorization: Token <LINKDING_TOKEN>`

## 查询参数

| 参数 | 说明 |
|------|------|
| `date_filter_by` | 按添加时间：`added` |
| `date_filter_type` | 类型：`relative`（相对）或绝对 |
| `date_filter_relative_string` | 相对时间：`yesterday`、`this_week` 等 |
| `limit` | 条数，如 `100` |

## Bash 一句命令

### 环境变量

执行前可设置：

```bash
export LINKDING_TOKEN='你的API Token'
```

### 昨日书签

```bash
curl -s -H "Authorization: Token ${LINKDING_TOKEN}" \
  "https://linkding.chensoul.cc/api/bookmarks/?date_filter_by=added&date_filter_type=relative&date_filter_relative_string=yesterday&limit=100"
```

### 本周书签

```bash
curl -s -H "Authorization: Token ${LINKDING_TOKEN}" \
  "https://linkding.chensoul.cc/api/bookmarks/?date_filter_by=added&date_filter_type=relative&date_filter_relative_string=this_week&limit=100"
```

### 使用 jq 输出 Markdown 链接

每条书签输出为 `- [标题](URL)` 列表格式：

昨日：

```bash
curl -s -H "Authorization: Token ${LINKDING_TOKEN}" \
  "https://linkding.chensoul.cc/api/bookmarks/?date_filter_by=added&date_filter_type=relative&date_filter_relative_string=yesterday&limit=100" \
  | jq -r '.results[]? | "- [\(.title // "无标题")](\(.url))"'
```

本周：

```bash
curl -s -H "Authorization: Token ${LINKDING_TOKEN}" \
  "https://linkding.chensoul.cc/api/bookmarks/?date_filter_by=added&date_filter_type=relative&date_filter_relative_string=this_week&limit=100" \
  | jq -r '.results[]? | "- [\(.title // "无标题")](\(.url))"'
```

输出示例：

```markdown
- [GitHub - user/repo](https://github.com/user/repo)
- [示例文章](https://example.com/post)
```
