# 同步 Sub2sb 上游更新

2sb 是独立开发的仓库；`origin` 指向 2sb，`upstream` 指向 yaml2sb。以下命令在终端中逐条执行，不要复制说明文字。

## 常规同步

先确认当前分支和工作区状态：

```sh
git -C /Users/apple/Documents/GitHub/2sb status --short --branch
```

如有未提交改动，先提交或暂存，再继续。获取并预览上游更新：

```sh
git -C /Users/apple/Documents/GitHub/2sb fetch upstream
git -C /Users/apple/Documents/GitHub/2sb log --oneline --graph --decorate --left-right main...upstream/main
```

确认要同步后，合并上游 `main`：

```sh
git -C /Users/apple/Documents/GitHub/2sb switch main
git -C /Users/apple/Documents/GitHub/2sb merge upstream/main
```

如果出现冲突，按 Git 提示修复冲突文件，然后检查并运行测试：

```sh
git -C /Users/apple/Documents/GitHub/2sb diff --check
cd /Users/apple/Documents/GitHub/2sb && python3 -m unittest discover -s tests
```

测试通过后推送到 2sb 私有仓库：

```sh
git -C /Users/apple/Documents/GitHub/2sb push origin main
```

## 只获取、不合并

只想查看上游有没有新提交时，运行：

```sh
git -C /Users/apple/Documents/GitHub/2sb fetch upstream
git -C /Users/apple/Documents/GitHub/2sb log --oneline --graph --decorate --left-right main...upstream/main
```

`<` 表示只在当前 `main` 上的提交，`>` 表示只在 `upstream/main` 上的提交。获取上游不会自动修改当前分支或推送到远程。
