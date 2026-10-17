# 配置与自定义修改文件

面向《无尽地牢 2D 版》16.0 的桌面配置工具，包含两个部分：

- 会话修改器：独立窗口调整敌人、玩家、资源和环境规则。
- 规则配置：检查、编译和模拟已有的 `.dungeon` 生态配置。

修改器不修改 `16.0` 的游戏源码。它以临时会话启动游戏，所有倍率和初始资源
只存在于当前进程内，存档也写入工具目录，不在游戏目录留下修改后的设置或进度。

## 启动窗口

双击：

```text
启动配置与自定义修改文件.bat
```

也可以在 PyCharm 或 PowerShell 中运行：

```powershell
python -B -m modifier.gui
```

窗口中的“以修改模式启动游戏”会启动 `配置工具/../16.0`。如果游戏是从其他
入口直接启动的，已经运行中的进程无法热注入；需要关闭后由本工具重新启动。

## 会话修改项

| 修改项 | 默认 | 生效范围 |
| --- | ---: | --- |
| 普通敌人生命 | 1.0 | 新生成敌人 |
| 精英敌人生命 | 1.0 | 新生成精英 |
| 首领生命 | 1.0 | 新生成首领 |
| 玩家受到伤害 | 1.0 | 即时 |
| 玩家攻击 | 1.0 | 即时 |
| 玩家移速 | 1.0 | 即时 |
| 玩家生命上限 | 1.0 | 新一局 |
| 额外初始水晶 | 0 | 新一局 |
| 额外初始炸弹 | 0 | 新一局 |
| 寺庙水晶伤害 | 1.0 | 即时 |
| 寺庙水晶冷却 | 1.0 | 即时 |
| 风雪与风灵推力 | 1.0 | 即时 |

倍率使用 `1.0` 表示原版数值。额外资源可以为负数，但结果不会低于 0。

滑块修改会立即写入当前会话配置。设置窗口保持打开时，即时项可以在游戏运行中
继续调整；下一次进入新房间或触发对应行为时使用新值。

## 存档隔离

启动时默认复制游戏目录中的 `save_data.json` 和 `run_save.json` 到：

```text
配置工具/runtime/sessions/<时间戳>-<编号>/
```

游戏只读写这份临时副本：

- 游戏目录中的局外设置、统计、成就和存档不会被改写。
- “继续上一局”在当前临时会话中仍可使用。
- 未勾选“保留临时会话”时，游戏退出后删除副本。
- 最近一次运行日志保留在 `runtime/last_game.log`。
- 游戏以 `-B` 启动，不在游戏源码目录生成 `__pycache__`。

临时会话保留下来也只位于配置工具目录，不会合并回游戏本体存档。

## 规则配置

“规则配置”页签可以选择 `.dungeon` 文件并执行：

- 检查：给出带行列号的语法和语义诊断。
- 编译 JSON：生成稳定的 `build/world.json`。
- 模拟十万房间：检查普通房比例、生态长度、嵌套房频率和唯一性。

命令行接口仍然可用：

```powershell
python -B -m dungeon_dsl check examples/world.dungeon
python -B -m dungeon_dsl compile examples/world.dungeon -o build/world.json
python -B -m dungeon_dsl simulate examples/world.dungeon --rooms 100000 --seed 42
python -B -m dungeon_dsl explain examples/world.dungeon tomb
```

## 运行环境

- Python 3.10+
- pygame 2.6.1
- 当前验证环境：Python 3.13.5
- 修改器窗口使用 Python 标准库 Tkinter

## DSL 结构

```text
version 1

catalog {
    biome tomb
    enemy skeleton
    elite bone_carrier scene tomb
}

room_rule combat {
    allow_nested true
}

region tomb {
    title "亡灵墓穴"
    length 3..5
    normal_gap 0.9
    normal_gap_step 0.1

    enemy_pool {
        skeleton weight 20
        ghost weight 10
    }

    nested church {
        chance 0.15
        extend 2
        once_per_region true
        allowed_room_rules [combat]
    }
}
```

`nested` 可以写在 `region` 内，也可以作为顶层声明并用 `parent` 指定父区域。
同一生态可以声明多个不同的嵌套房间。

`normal_gap` 表示生态结束后的第二个普通房间仍为普通的概率。生态结束后的
第一个房间必定普通；若继续得到普通房间，概率会按 `normal_gap_step`
依次递减。

## 错误示例

```text
examples/world.dungeon:12:9: error[E201]: unknown enemy 'zombi'
  help: did you mean 'zombie'?
```

检查器区分错误和警告。概率过高、嵌套延长过大或未限制每区域唯一性会产生警告。

## 目录

```text
modifier/
  config.py        修改项校验与读写
  launcher.py      临时会话与游戏启动
  runtime.py       游戏进程内运行时补丁
  gui.py           双页签桌面窗口
dungeon_dsl/
  lexer.py         词法分析
  parser.py        递归下降解析
  ast.py           AST 与源码位置
  diagnostics.py   诊断与错误渲染
  validator.py     符号表与语义检查
  compiler.py      JSON 编译
  simulator.py     概率模拟
  cli.py           命令行入口
examples/
tests/
```

## 测试

```powershell
python -B -m unittest discover -s tests -v
```

测试包含对真实 16.0 玩家、普通敌人、精英和首领实体的倍率探针，以及存档副本
路径隔离检查。
