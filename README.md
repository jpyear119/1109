# 1109 · XPZHU × HGKS V2 集成发布候选（2026-11-13）

> **本文件夹是XPZHU/HGKS源码的增量集成包，不是完整独立运行的XPZHU仓库。**
> 如果 `C:\Project08\11\1109` 已经是XPZHU源码checkout，可以在独立下载目录解压本包，然后使用 `tools/install_to_repos.py` 生成补丁并应用到1109。
> 如果1109只是一个新建空目录，必须先有XPZHU正式源码；不能将本增量包直接当成完整XPZHU运行。

**当前证据**：21项离线测试通过、真实历史P05 Job（32张图）离线导出27个Action与37个审核对象，XML结构校验PASS。**未运行**用户Windows Python3.9/3.12、HGKS冻结predict.py的真实模型、PC完整链路或Theme B；不要把它们称为已完成。

**目标路径**：`C:\Project08\11\1109`；冻结HGKS仍在 `C:\Project08\1020`，Claude开发仓库默认 `C:\Project08\1101`。请实际核对路径。代码文件顶部包含中文的输入、处理、输出及运行命令注释。

**GitHub公开发布说明**：本仓库 `jpyear119/1109` 为公开仓库，已按用户明确决定公开此集成增量代码。这里不包含预训练模型、原始视频、P05原始实验数据或私人密钥；请勿将本地数据和运行日志直接提交。此仓库并非完整XPZHU源码。

## 从1109开始的安全操作（PowerShell）

1. 先确认 `Test-Path 'C:\Project08\11\1109\.git'` 和 `Test-Path 'C:\Project08\11\1109\modules\m1\src\route_b_m1\service.py'` 都为True；然后用 `git -C 'C:\Project08\11\1109' status --short` 查看是否有未提交工作。
2. 将**本增量包**解压在仓库目录之外，例如 `C:\Project08\11\1109_integration_bundle`，不要解压后覆盖1109源码。
3. `python 'C:\Project08\11\1109_integration_bundle\tools\install_to_repos.py' --xpzhu-root 'C:\Project08\11\1109' --hgks-root 'C:\Project08\1101' --patch-output 'C:\Project08\11\1109_patch_review'`；默认只生成补丁并检查，不修改两仓库。需要确认HEAD与源码匹配，不能直接跳过检查。
4. 在看过补丁、备份并确认两工作树干净后，可显式加 `--apply`。随后在已安装源码的1109根目录运行： `python tools/hgks_task_flow.py --help`。
5. 真实P05离线回放命令在 `xpzhu/tools/hgks_task_flow.py` 源码顶部。若任务包不在本地，请先解压原始P05 Job并指定实际路径。

注意：当前仅完整验证了P05的历史Job→Task XML；用`DEV23.json.gz`启动正式选帧需本机1020锁定环境与权重；不同于P05历史K32。后续不得未经授权自动发起付费Claude请求。

---

# XPZHU × HGKS V2 · 可读性修订版 V3（2026-11-13）

## 完成范围

代码路线：**HGKS正式预处理候选池 → 冻结predict.py → 选中时间戳 → 真实JPEG映射 → Claude PC_D Job → 结构化Action Events/BT JSON → M6B确定性XML → 人工审查记录**。

本包提供源码、测试、输入格式和一个**默认只生成补丁**的安装工具。没有修改两个私有GitHub仓库，没有在用户Windows电脑运行模型。M6B的XML是**可审阅但不可执行的候选**，不冒称Theme B已接入。

## 项目路径

- `C:\Project08\1020`：冻结HGKS V2推断代码与模型快照；正式预处理包位于 `data\canonical\portable\{DEV23,TEST23,TRAIN70}.json.gz`。其中DEV/TEST供模型推断，TRAIN不参与测试期推断。
- `C:\Project08\1101`：HGKS当前开发仓库、`claude_vision`正式Job生成与历史实验。本包在这里增加版本化的`PC_D` Prompt；历史`D`不改。
- `C:\Project08\1019`：可能仍有原视频、官方时钟和部分未迁移的只读资产。**这些文件路径源于交接包，不代表我们已检查Windows磁盘。**
- XPZHU本地根目录：当前未确认，以下写作`C:\Project08\11\1109`。

**注意两个HGKS根目录不是一回事：**M1 `hgks_root`指向1020冻结推断；Claude准备Job的`--claude-root`指向安装了新Prompt的1101。

## 文件组织与权威执行路径

### XPZHU 新增

| 代码 | 唯一职责 |
|---|---|
| `modules/m1/src/route_b_m1/hgks_v2_backend.py` | 预检查与子进程调用原版HGKS `predict.py`，读回选帧结果 |
| `modules/m1/src/route_b_m1/hgks_images.py` | 映射真实JPEG或用FFmpeg解码并验证实际PTS/哈希 |
| `src/route_b_pipeline/sop_steps.py` | 校验PC SOP步骤时间与来源，生成Prompt上下文 |
| `modules/m6b_bt_export/src/route_b_m6b/task_draft.py` | Job→候选IR、审查清单、经修订提案、可审阅XML的门禁 |
| `modules/m6b_bt_export/src/route_b_m6b/task_draft_cli.py` | M6B输出命令入口 |
| `tools/hgks_task_flow.py` | 单一、薄的四步命令入口：`select`、`images`、`prepare`、`export` |
| `tests/integration/test_hgks_*.py` | 无真实模型费用的组件/结构/错误输入测试 |

### XPZHU既有文件的增量修改（由安装工具生成真正Git补丁）

- `modules/m1/src/route_b_m1/workspace.py`：建立没有视频上传的缓存Run。
- `modules/m1/src/route_b_m1/service.py`：加入`hgks_v2_cached`运行模式，保留旧M1。
- `apps/local_ui/controller.py`：暴露`create_hgks_cached_run`和缓存模式调用；**不修改现有Gradio界面布局**。
- `modules/m6b_bt_export/src/route_b_m6b/xml_writer.py`：在现有唯一XML编译模块中增加嵌套Task Proposal树的编译函数；旧M6B模式不变。

### HGKS开发仓库（1101）

- 新增`claude_vision/schema_pc.py`：面向PC翻新任务的`PC_D`新Prompt，复用原D的输出Schema。
- 新增`claude_vision/xpzhu_bridge.py`：复用`job.create_job`，只建不可变Job，不付费调用。
- 小改`claude_vision/schema_v2.py`、`claude_vision/job.py`：注册`PC_D`路由，历史Prompt路径不改。

**不更改**`data.py`、`prepare.py`、`predict.py`、`train.py`、`vision.py`等冻结算法；不重新实现141维特征或HGB打分。

## 安装：先只生成Git补丁，再应用

本包下载后解压至任意目录`<BUNDLE>`。从任一受支持的Python运行：

```powershell
python <BUNDLE>\tools\install_to_repos.py `
  --xpzhu-root C:\Project08\11\1109 `
  --hgks-root C:\Project08\1101 `
  --patch-output <BUNDLE>\generated_patches
```

这会**只读取两个实际checkout、生成`xpzhu.patch`和`hgks-v2-1101.patch`并对当前文件执行`git apply --check`，不修改源码**。它核对仓库HEAD分别为`9c90fb98aa18...`和`d8c48df2b1ef...`；若本地不是这两个版本，拒绝操作，应该先阅读差异再决定是否显式`--allow-different-head`，不能直接覆盖本地新工作。

审阅完成且两个checkout均无未提交变更后，可在同一个命令末尾加`--apply`。默认不执行。**不要在未备份的本地工作树盲目应用。**

## 输入 → 处理 → 输出：四步

### 1. M1选帧：输入预处理结果和真实模型

配置样例：`xpzhu/config/templates/hgks_v2_cached.example.json`。必须使用1020中实际存在的已冻结DEV/TEST portable文件、对应正式`joblib`权重及Python环境。

```powershell
python C:\Project08\11\1109\tools\hgks_task_flow.py select `
  --config C:\Project08\11\1109\config\templates\hgks_v2_cached.example.json
```

得到`run_id`和`runtime_runs/<run_id>/m1/HGKS_SELECTED_TIMESTAMPS.json`。数据内容是视频ID、候选索引、选中秒数和哈希；**没有JPEG**。此时HGKS按照正式`ceil(duration_s/30)`预算运行，不自动复现P05历史K32设置。`--video-id`仅影响下一步图片映射，不改变正式HGKS对DEV/TEST数据包的整体推断。

### 2. JPEG映射：输入选中时间戳及图像来源清单

图像来源文件格式见`xpzhu/config/templates/hgks_frame_sources.example.json`。每个视频二选一：

- `mode=indexed_jpegs`：原JPEG索引，必须有各帧实际时间戳、文件路径、SHA。`timebase=hgks_selection_seconds`表示与HGKS候选时间属于同一个时钟。
- `mode=indexed_jpegs`且`timebase=official_mp4_frames`：若使用HD-EPIC官方MP4帧映射，**应先在1020的权威`run1019.py/vision.snap_to_mp4()`取得物理帧索引与时间**，每条`frames`同时填写`requested_time_s`、`timestamp_s`、`official_frame_index`、图像路径和SHA。本代码不另写一套官方时钟映射。
- `mode=video_ffmpeg`：必须显式填写`timebase=mp4_relative_seconds`、`video_path`、`video_sha256`与`ffmpeg_executable`。它从视频起点逐帧解码至请求秒数，核查真正PTS；速度较慢，且**不能直接代替HD-EPIC的VRS→MP4官方时钟映射**。

```powershell
python C:\Project08\11\1109\tools\hgks_task_flow.py images `
  --run-id <RUN_ID> --video-id <EXACT_VIDEO_ID> `
  --frame-sources <SOURCES.json> --tolerance-s 0.25
```

输出`runtime_runs/<run_id>/m1/materialized_images/M1_SELECTED_IMAGES.json`及真实JPEG。

### 3. M2视觉Job准备：输入JPEG、PC SOP和时间段

SOP **必须明确每一步的起止时间与时间来源**，格式见`pc_task_sop_steps.example.json`。它是步骤说明，**不是观察证据**。

```powershell
python C:\Project08\11\1109\tools\hgks_task_flow.py prepare `
  --run-id <RUN_ID> --video-id <EXACT_VIDEO_ID> `
  --claude-root C:\Project08\1101 `
  --python-executable <PYTHON_3_12_EXE> `
  --sop <PC_SOP_STEPS.json> --start <SEGMENT_START_SECONDS> `
  --end <SEGMENT_END_SECONDS> --job-id <UNIQUE_JOB_ID>
```

这一步通过HGKS已有`claude_vision.job.create_job()`建立`PC_D` Job，输出`MANIFEST.json`、`REQUEST.json`、`PROMPT.md`、`SCHEMA.json`，**完全不调用付费Claude**。

以后做真实调用时，使用1101仓库现有`claude_vision/run_one.py`的**显式`--i-authorize-paid-call`**流程；输入相同的`--job-root`、`--job-id`、`--images`、`--sop`、`--prompt-family PC_D`等参数，原代码负责执行、真实模型身份检查、回执和导出`BT_OUTPUT.json`。本包不会自动付费或自动生成看似真实的BT结果。

### 4. M6B任务级XML：输入真实已入库Claude Job

```powershell
python C:\Project08\11\1109\tools\hgks_task_flow.py export `
  --job-dir <COMPLETED_JOB_DIR> --output <NEW_CANDIDATE_DIR>
```

输出`TASK_DRAFT_IR.json`、`BT_DRAFT_CANDIDATE.xml`、`NODE_MODELS.xml`、`BT_XML_VALIDATION.json`、`TASK_REVIEW_TEMPLATE.json`。不生成`BT_REVIEWED_CANDIDATE.xml`，除非所有Event、Condition及控制节点都具有**显式审查决定**。原来的Claude Job及BT JSON不会被改写。

修订错误树结构时，提供独立的`--correction <CORRECTION.json>`（schema=`task_draft_correction_v1`；包含`source_job_output_sha256`、`author`、`reason`、完整`events`及`bt`），审查提案哈希将变化，旧批准失效。对最终修订版本的`TASK_REVIEW_TEMPLATE.json`逐项作出`accept/reviewer_id/reviewed_at/comment`决定，再使用`--decisions`重新编译到**新的**输出目录。错误条件不能自动批准。

XML中的`RouteBActionCandidate`和`RouteBConditionCandidate`只是带引用的候选节点，不是Theme B技能或可执行节点。

## 已做检查与限制

- 使用独立兼容性测试环境运行本包19项无付费测试：输入错误、模型SHA、JPEG映射、SOP步骤、Task IR、显式审查、修订后审查失效等。
- 用用户附带的真实P05已完成D Job运行了离线导入和XML候选：27个Action、37个审核对象。**没有重新调用Claude，也没有改写原P05。**
- 另以短合成MP4调用真实FFmpeg执行时间戳→JPEG映射，并核对报告PTS。
- 使用合成Git仓库（包括原始CRLF `job.py`）检验安装器能输出真正可`git apply --check`的补丁；**未在完整私有XPZHU checkout验证真实HEAD或执行其整套回归测试**。
- 未在你的Windows机器运行冻结模型；未验证PC原视频、步骤时间、手/物输入迁移、跨操作者效果、BT逻辑正确性、BehaviorTree.CPP运行时或Theme B接口。

## 延期原因明确的部分

Theme B的AO-OP正式字段及机器人技能Registry尚未获取，不能创造一个未经其确认的协议假装已经完成。当前终点是**具有可追溯证据和人工审核入口的Task-level XML候选**，而不是Theme B可执行交付。

## V3附带的历史V2审查修订

V2已经在代码中解决以下问题，用户不应在本地手工打这些补丁：

1. `hgks_task_flow.py prepare` 从一整段视频的选中图像中筛选指定`--start`至`--end`的子段。原V1错误地要求**全部**选中图像都在子段内；现在只有子段无图时才拒绝准备Job。
2. `hgks_task_flow.py images`增加可选`--video-id`。DEV23/TEST23会一次推断23个视频，但任务级导出可只映射一个视频的JPEG，不再强迫准备另外22个视频的帧来源。
3. `hgks_images.py`从索引中选择未被使用且时间误差在容差内的真实JPEG，使用Pillow实际解码而不仅仅验证三个魔数；输出`mapping_error_s`及`source_timebase`，识别错误图像及错误时间映射。
4. `task_draft.py`核查原Job的Prompt、SOP、Schema、整体图片清单哈希、尺寸/字节数、模型身份及入库回执。历史Job在Windows存在CRLF换行，计算其文本哈希时按原`sha256_text`的语义做通用换行读取，避免错误拒绝P05的真实实验产物。
5. `PC_D`有独立的输出Schema，不允许当前M6B不支持的`Parallel`；原研究D Schema未更改。新Prompt解释Fallback的SUCCESS短路语义。`PC_D`提示词版本更新为`CLAUDE_VISION_PC_D_V2_20261113`。
6. `task_draft.py`的Control Review表不只显示`Fallback with 2 children`，而是显示具体Condition及子节点类型，提醒人工审核短路语义；审查仍须人工逐项接受，不能冒充已执行。
7. `install_to_repos.py`保留真实GitHub中HGKS`claude_vision/job.py`的CRLF字节格式，修正可能导致`git apply`失败的安装问题；生成补丁的目录必须在两个checkout之外，若第二仓库应用失败，将尝试安全回滚先前已应用的补丁。
8. `hgks_v2_backend.py`验证选中结果是否满足冻结的`ceil(duration_s/30)`预算及唯一候选索引，防止把不同预算实验混称正式算法。

**依赖说明：**V2的M1 JPEG来源映射要求XPZHU Python环境已安装Pillow。该依赖只用于真实JPEG解码验证，正式HGKS数值模型仍在独立Python环境运行。用户本地需要确认Pillow能被XPZHU的Python3.9解释器导入，不应照搬当前审查环境中的Pillow版本。

**局限不变：**当前冻结的`predict.py`官方CLI只接受`HGKS_PORTABLE_INPUT_V1`的DEV/TEST预处理包；新PC视频的Hand/Object/Coarse特征尚未得到可运行的数据实例。当前V2可以用已经完成的正式DEV/TEST候选池走集成链路，不代表任意新PC视频的预处理数据已兼容。原`PC_D`完整Claude收费调用、正式仓库回归、Theme B AO-OP协议和运行时机器人执行均尚未验证。

### V2推荐的最小本地工作

1. 确认XPZHU和HGKS1101两个checkout的HEAD及本地是否已有未提交改动。把补丁输出目录放在两个checkout外，先运行`install_to_repos.py`（不带`--apply`）检查。
2. 在XPZHU Python环境中检查`PIL`是否能导入；将`config/templates/hgks_v2_cached.example.json`中三个本地路径改成机器上的真实路径。
3. 首先使用1020正式DEV23/TEST23候选及模型执行M1；实际验证选中候选与原HGKS输出逐项一致。
4. `images`阶段可使用`--video-id`只生成所需的视频对应的JPEG，并核对源图和时间基；`prepare`可使用子任务`--start`和`--end`。
5. 测试真实Claude与M6B前，使用P05包重放离线候选并审核控制流。P05转换成功不等于BT逻辑正确。Theme B接口要等正式规范提供后再写。

## V3：讲解已写进源码

在VS Code中从 `xpzhu/tools/hgks_task_flow.py` 文件顶部开始看，不需要先读
本README。各核心模块/函数的 docstring 直接说明**输入、处理、输出、错误
条件和为什么保留该约束**；悬停函数名即可看到。研究仓库的冻结算法不改。

现场阅读的唯一路径：
`hgks_task_flow.select()` → `hgks_v2_backend.run_cached()` →
`1020/predict.select_video()` → `hgks_images.materialize_images()` →
`hgks_task_flow.prepare()` → `1101/job.create_job()` →
`task_draft.export_candidate()` → `xml_writer.synthesize_task_draft_xml()`。

修复了同视频不同Job的两段SOP任务会覆盖
`CLAUDE_IMAGES_<video_id>.json`/`TASK_SOP_<video_id>.md`的问题：现在
按 `job_id` 命名，重复ID直接拒绝覆盖；新增回归测试。

**验收边界**：可读性改动不代表真实Windows环境/冻结HGKS推断
或新PC视频已经验证。请先在两个本地仓库运行补丁预检查与回归测试。


## V4：可在源码顶部复制的P05真实离线回放命令

- `xpzhu/tools/hgks_task_flow.py`：PowerShell命令完整放在文件顶部注释，先解压P05原始Job，执行`export`，核对任务输出；后面还包括四阶段正式命令模板。
- `xpzhu/modules/m6b_bt_export/src/route_b_m6b/task_draft_cli.py`：同一编译器的直接命令和检查命令。
- `tools/install_to_repos.py`：从生成补丁到审阅/可选应用的完整命令（默认不改仓库）。
- `xpzhu/tests/integration/test_hgks_p05_replay.py`：设置`P05_JOB_DIR`后用真实P05运行的两项测试，包含32张JPEG完整解码、27个Action及37个审核对象。

**P05范围限制**：该包是已完成D Job，验证的是32张图片及Job到XML；不是重新运行冻结HGKS选帧，也不是新付费Claude调用。实时Windows路径要由本地文件位置决定，源码顶部给出的路径是示例而非实测。
