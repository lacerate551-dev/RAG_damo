# MinerU 模型部署指南

> 解决服务器部署时的模型路径配置问题

---

## 一、当前配置分析

### 1.1 MinerU 模型路径机制

MinerU 通过以下方式确定模型路径：

```python
# 1. 读取环境变量 MINERU_MODEL_SOURCE
model_source = os.getenv('MINERU_MODEL_SOURCE', "huggingface")

# 2. 如果是 local 模式，读取配置文件
if model_source == 'local':
    config = read_config()  # 读取 ~/mineru.json
    models_dir = config.get('models-dir')
    
# 3. 否则从 HuggingFace 自动下载到缓存目录
else:
    # 默认下载到 ~/.cache/huggingface/hub/
    pass
```

### 1.2 配置文件位置

MinerU 配置文件查找顺序：

1. **环境变量指定**：`MINERU_TOOLS_CONFIG_JSON`
2. **默认位置**：`~/mineru.json`（用户主目录）

**Windows**：`C:\Users\<username>\mineru.json`  
**Linux**：`/root/mineru.json` 或 `/home/<user>/mineru.json`

### 1.3 当前项目使用方式

查看 `parsers/mineru_parser.py` 第 186-197 行：

```python
cmd = [
    str(mineru_exe),
    "-p", str(file_path),
    "-o", str(output_dir),
    "-m", "auto",
    "-b", backend,
    "-l", lang,
    # ...
]
```

**关键发现**：
- ✅ 代码中**没有硬编码路径**
- ✅ 使用命令行调用 `mineru` 可执行文件
- ✅ MinerU 自动读取配置文件或环境变量

---

## 二、问题场景

### 场景 1：开发环境（本机）

```
模型位置：C:\Users\qq318\.cache\huggingface\hub\
配置文件：C:\Users\qq318\mineru.json（可能不存在）
模型来源：首次运行时自动从 HuggingFace 下载
```

### 场景 2：生产环境（服务器 Docker）

```
问题：
1. Docker 容器内用户目录是 /root/
2. 模型没有打包到镜像中
3. 首次启动会尝试下载模型（可能失败或很慢）
```

---

## 三、解决方案

### 方案 A：本地模型模式（推荐）✅

**适用场景**：
- 服务器无法访问 HuggingFace
- 需要离线部署
- 希望加快启动速度

#### Step 1：下载模型到项目目录

在**本机**执行：

```bash
# 激活虚拟环境
cd C:\Users\qq318\Desktop\rag-agent
venv\Scripts\activate

# 创建模型目录
mkdir models\mineru

# 下载所有模型
mineru-models-download -s huggingface -m all -d models\mineru
```

**说明**：
- `-s huggingface`：从 HuggingFace 下载
- `-m all`：下载所有模型（pipeline + vlm）
- `-d models\mineru`：指定下载目录

#### Step 2：创建配置文件

在项目根目录创建 `mineru.json`：

```json
{
  "models-dir": {
    "pipeline": "/app/models/mineru/pipeline",
    "vlm": "/app/models/mineru/vlm"
  }
}
```

**注意**：路径使用 Docker 容器内的路径 `/app/`。

#### Step 3：修改 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install gunicorn>=21.0.0

# 应用代码
COPY . .

# 复制模型文件（重要！）
COPY models /app/models

# 复制配置文件到容器内用户目录
COPY mineru.json /root/mineru.json

# 设置环境变量
ENV MINERU_MODEL_SOURCE=local
ENV MINERU_TOOLS_CONFIG_JSON=/root/mineru.json

# 创建数据目录
RUN mkdir -p data knowledge/vector_store .data documents

EXPOSE 5001

# 生产模式启动
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
```

#### Step 4：构建镜像

```bash
# 构建镜像（会包含模型文件）
docker build -t rag-service:latest .

# 查看镜像大小
docker images rag-service
```

**预期镜像大小**：约 5-8GB（包含模型）

---

### 方案 B：挂载模型目录（灵活）

**适用场景**：
- 多个容器共享模型
- 模型文件太大，不想打包到镜像
- 需要动态更新模型

#### Step 1：在服务器上准备模型

```bash
# 在服务器上创建模型目录
mkdir -p /data/mineru-models

# 方式1：从本机上传
scp -r models/mineru/* user@server:/data/mineru-models/

# 方式2：在服务器上下载
ssh user@server
cd /data/mineru-models
pip install mineru[all]
mineru-models-download -s huggingface -m all -d /data/mineru-models
```

#### Step 2：创建配置文件

在服务器上创建 `/data/mineru.json`：

```json
{
  "models-dir": {
    "pipeline": "/models/pipeline",
    "vlm": "/models/vlm"
  }
}
```

#### Step 3：Docker Compose 配置

```yaml
# docker-compose.yml
version: '3.8'

services:
  rag-service:
    image: rag-service:latest
    ports:
      - "5001:5001"
    volumes:
      # 挂载模型目录
      - /data/mineru-models:/models:ro
      # 挂载配置文件
      - /data/mineru.json:/root/mineru.json:ro
      # 挂载数据目录
      - ./data:/app/data
      - ./documents:/app/documents
      - ./knowledge:/app/knowledge
    environment:
      - MINERU_MODEL_SOURCE=local
      - MINERU_TOOLS_CONFIG_JSON=/root/mineru.json
      - APP_ENV=prod
      - ENABLE_SESSION=false
    restart: unless-stopped
```

#### Step 4：启动服务

```bash
docker-compose up -d
```

---

### 方案 C：自动下载模式（不推荐）

**适用场景**：
- 服务器可以访问 HuggingFace
- 不介意首次启动慢

#### 配置

```dockerfile
# Dockerfile 不需要复制模型
# 首次启动时自动下载到 /root/.cache/huggingface/

# docker-compose.yml
services:
  rag-service:
    volumes:
      # 持久化模型缓存
      - mineru-cache:/root/.cache/huggingface
    environment:
      - MINERU_MODEL_SOURCE=huggingface  # 或不设置

volumes:
  mineru-cache:
```

**缺点**：
- 首次启动需要下载 5-8GB 模型
- 依赖网络连接
- 可能因为网络问题失败

---

## 四、验证部署

### 4.1 检查模型路径

进入容器检查：

```bash
# 进入容器
docker exec -it rag-service bash

# 检查配置文件
cat /root/mineru.json

# 检查模型目录
ls -lh /app/models/mineru/pipeline/
ls -lh /app/models/mineru/vlm/

# 测试 MinerU
python -c "from mineru.utils.config_reader import read_config; print(read_config())"
```

### 4.2 测试解析

```bash
# 在容器内测试
cd /app
python parsers/mineru_parser.py documents/test.pdf
```

### 4.3 查看日志

```bash
# 查看容器日志
docker logs -f rag-service

# 应该看到类似输出：
# [INFO] MinerU 配置: local 模式
# [INFO] 模型路径: /app/models/mineru/pipeline
```

---

## 五、模型文件清单

### Pipeline 模型（必需）

```
models/mineru/pipeline/
├── Layout/
│   ├── model.pt
│   └── config.json
├── MFD/
│   ├── yolov8_mfd.pt
│   └── config.json
├── MFR/
│   ├── unimernet_small.pt
│   └── config.json
├── OCR/
│   ├── det_db.pth
│   ├── rec_crnn.pth
│   └── config.json
└── TableRec/
    ├── table_rec.pt
    └── config.json
```

**总大小**：约 3-4GB

### VLM 模型（可选，高精度模式）

```
models/mineru/vlm/
├── qwen2-vl/
│   ├── model.safetensors
│   ├── config.json
│   └── tokenizer/
└── ...
```

**总大小**：约 4-5GB

---

## 六、常见问题

### Q1: 镜像太大怎么办？

**A**: 使用方案 B（挂载模型目录），镜像只包含代码，模型在宿主机。

### Q2: 如何更新模型？

**A**: 
- 方案 A：重新构建镜像
- 方案 B：直接替换宿主机上的模型文件，重启容器

### Q3: 模型下载失败怎么办？

**A**: 
1. 使用国内镜像：`export HF_ENDPOINT=https://hf-mirror.com`
2. 手动下载后上传到服务器
3. 使用方案 A 在本机下载后打包

### Q4: 如何减少模型大小？

**A**: 
- 只下载 pipeline 模型（不下载 vlm）
- 使用 `mineru-models-download -m pipeline` 而不是 `-m all`

### Q5: 配置文件不生效？

**A**: 检查：
1. 环境变量 `MINERU_MODEL_SOURCE=local` 是否设置
2. 配置文件路径是否正确：`/root/mineru.json`
3. 配置文件格式是否正确（JSON 语法）
4. 模型目录路径是否存在

---

## 七、推荐方案总结

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **方案 A：打包到镜像** | 部署简单、启动快 | 镜像大、更新麻烦 | 单机部署、离线环境 |
| **方案 B：挂载目录** | 灵活、易更新、多容器共享 | 需要管理宿主机文件 | 多节点、生产环境 |
| **方案 C：自动下载** | 镜像小 | 首次启动慢、依赖网络 | 测试环境 |

**生产环境推荐**：方案 B（挂载模型目录）

---

## 八、部署检查清单

部署前检查：

- [ ] 模型文件已下载到 `models/mineru/` 目录
- [ ] 创建了 `mineru.json` 配置文件
- [ ] Dockerfile 中添加了 `COPY models` 和环境变量
- [ ] 测试了本地解析功能
- [ ] 确认模型文件大小（3-8GB）

部署后检查：

- [ ] 容器启动成功
- [ ] 配置文件存在：`docker exec rag-service cat /root/mineru.json`
- [ ] 模型目录存在：`docker exec rag-service ls /app/models/mineru`
- [ ] 测试解析功能：上传一个 PDF 测试
- [ ] 查看日志无错误

---

**文档版本**: v1.0  
**最后更新**: 2026-04-20  
**维护者**: RAG 服务开发组


---

## 附加篇：MinerU安装深度解析与Windows框架全景 (Technical Analysis and Deployment Framework for MinerU)

Comprehensive Technical Analysis and Deployment Framework for MinerU Document Parsing Systems on Windows Platforms
The rapid proliferation of large language models (LLMs) has fundamentally transformed the landscape of data engineering, necessitating high-fidelity document parsing tools that can bridge the gap between unstructured PDF, image, and office formats and machine-readable structured data. MinerU, an open-source document parsing toolkit born from the pre-training requirements of the InternLM series, has emerged as a preeminent solution for converting complex documents into Markdown and JSON formats while preserving structural integrity, mathematical formulas, and tabular data.[1, 2] As an orchestrator of multiple deep learning components—including layout detection, optical character recognition (OCR), and vision-language model (VLM) reasoning—MinerU provides a robust pipeline for downstream retrieval-augmented generation (RAG) and agentic workflows.[3, 4] However, the deployment of such a sophisticated system on Windows operating systems presents a unique set of architectural and dependency-related challenges, primarily due to its heavy reliance on libraries traditionally optimized for Linux environments. This report provides an exhaustive investigation into the installation methodologies, operational configurations, and troubleshooting frameworks required to successfully implement MinerU on Windows platforms.
Architectural Evolution and Component Logic
Understanding the implementation of MinerU requires a nuanced appreciation of its underlying architecture and how its components interact within a Windows-based environment. Originally conceived as the Magic-PDF project, the tool has evolved into a comprehensive suite capable of handling not only PDFs but also DOCX, PPTX, and XLSX inputs.[5, 6] The system is designed to remove semantic noise—such as headers, footers, and page numbers—while accurately reconstructing the human reading order in multi-column or complex layouts.[3, 4]
Inference Backends and Hardware Specificity
The versatility of MinerU is largely attributed to its support for diverse inference backends, which allow users to balance accuracy against available hardware resources. On Windows, the choice of backend is the most significant predictor of installation complexity and operational stability.
Backend Type
Core Technologies
Hardware Optimization
Minimum VRAM
Accuracy (OmniDocBench)
Pipeline
Layout detection + OCR
CPU (MKL/AVX) or GPU (Volta+)
4 GB
86.2 [5, 7]
Hybrid
Layout + OCR + VLM Reasoning
NVIDIA GPU (Volta+)
8 GB
90+ [5]
VLM-Transformers
Transformers-based Vision models
NVIDIA GPU (Ampere+)
8 GB
90+ [8]
VLM-SGLang
SGLang Optimized Inference
NVIDIA GPU (Ampere+)
24 GB
90+ [8]
The "Pipeline" backend is the most compatible with Windows systems, especially those lacking high-end GPUs, as it supports pure CPU inference through Intel MKL and AVX instruction sets.[5, 9] The recent release of version 3.0.0 introduced a systematic upgrade to this architecture, replacing several AGPLv3-licensed models with high-precision alternatives that achieve higher accuracy on the OmniDocBench benchmark.[5] This version also pioneered native DOCX parsing, which bypasses the traditional PDF-to-Markdown conversion, improving end-to-end speed by tens of times.[5]
The Role of OCR and Vision Models
A fundamental feature of the MinerU ecosystem is its dual-engine approach to content extraction. For text-based PDFs, it utilizes sophisticated reading order analysis; for scanned or "garbled" documents, it automatically triggers an OCR pipeline supporting 109 languages.[1, 5] In Windows environments, the OCR functionality is primarily powered by PaddleOCR, which necessitates a specific version of the PaddlePaddle framework that matches the system's CUDA environment.[9, 10] This requirement is often a source of friction during installation, as version mismatches between CUDA, cuDNN, and PaddlePaddle can lead to silent failures or runtime errors.[11, 12]
Foundational Requirements and Environment Preparation
A successful Windows installation is predicated on the rigorous preparation of the software toolchain and hardware drivers. Windows lacks the integrated development headers found in most Linux distributions, making the manual configuration of the C++ build environment mandatory.
Hardware Prerequisites and Resource Allocation
MinerU is a resource-intensive application, particularly during the model initialization and inference stages. Windows users must ensure their systems adhere to the following hardware guidelines to avoid performance bottlenecks or out-of-memory (OOM) conditions.
Component
Minimum Specification
Recommended Specification
Rationale
RAM
16 GB
32 GB or more
Required for loading multiple model weights simultaneously.[5, 7]
GPU
NVIDIA Volta (e.g., V100)
Ampere (30-series) or later
Newer architectures support advanced quantization and faster inference.[7, 8]
VRAM
4 GB (Pipeline mode)
24 GB (VLM mode)
VLM backends require substantial memory for high-resolution document imagery.[8]
Storage
20 GB (SSD)
50 GB+ (SSD)
Models and intermediate rendering files require fast I/O and significant space.[7, 13]
Processor
64-bit x86 with AVX
Multi-core Intel/AMD
AVX support is critical for the CPU version of PaddlePaddle.[9, 14]
The Windows C++ Build Toolchain
One of the most common points of failure in the installation process is the absence of Microsoft Visual C++ Build Tools. Many of the underlying Python libraries, most notably detectron2 and pycocotools, involve C++ and CUDA extensions that must be compiled during installation if pre-built wheels are unavailable.[15, 16]
To resolve this, the user must install the Visual Studio Community edition and select the "Desktop development with C++" workload.[15, 17] Within this workload, it is essential to verify the presence of:
MSVC v142 or v143 C++ x64/x86 build tools.
Windows 10 or 11 SDK (matching the host OS version).[15, 16]
C++/CLI support for the respective build tools.[15]
Following the installation of these tools, a system restart is strongly recommended to ensure that the compiler paths are correctly registered in the Windows environment.[16]
Python Version Strategy
MinerU currently supports Python versions 3.10 through 3.12, with some documentation suggesting the beginning of support for 3.13.[8, 18] However, for Windows users, Python 3.10 remains the recommended version. This is because many critical dependencies, such as the precompiled wheels for detectron2 provided by the community, are specifically built for Python 3.10.[13, 19, 20] Using newer versions of Python often forces the system to attempt a source compilation of detectron2, which is notoriously difficult to complete successfully on Windows without extensive manual patching.[21]
Detailed Installation Procedures
There are three primary avenues for installing MinerU on Windows: the pip/uv method, installation from source, and Docker-based deployment.
Path A: Streamlined Installation via uv
The uv package manager has become the preferred tool for MinerU installation due to its superior dependency resolution and execution speed compared to standard pip.[6, 8]
Environment Setup: It is a best practice to use a clean Conda environment to avoid library version conflicts.
Manager Installation: Ensure pip and uv are up to date.
Core Package Installation: The mineru[all] extra ensures that all components, including those for VLM and pipeline acceleration, are fetched.
Path B: Addressing the Detectron2 Hurdle
The detectron2 library is a frequent obstacle as it lacks official Windows support from Meta.[21, 22] If the standard installation fails, users should manually install a precompiled wheel tailored for Windows and Python 3.10.
pip install detectron2 --extra-index-url https://myhloli.github.io/wheels/
``` [13, 23]

This wheel bypasses the need for local compilation. If this index is inaccessible or the user is on a different Python version, they must clone the repository and build it manually, which requires the `CUDA_HOME` environment variable to be set correctly to the location of the installed CUDA Toolkit.[21] Failure to match the CUDA version used to compile `detectron2` with the CUDA version used for PyTorch will result in a runtime crash.[21]

### Path C: GPU and OCR Acceleration Setup

To enable GPU acceleration on Windows, the default PyTorch installation must often be overwritten with a version specifically linked to the system's CUDA version.[10, 13]

| CUDA Version | PyTorch Installation Command |
| :--- | :--- |
| **11.8** | `pip install --force-reinstall torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cu118` [10, 13] |
| **12.1+** | Refer to the PyTorch official website for the matching `torch` and `torchvision` versions.[24] |

Furthermore, to activate OCR acceleration, the `paddlepaddle-gpu` library must be installed. For users with CUDA 11.8, version 2.6.1 or 3.0.0b1 is recommended.[10] For users on newer CUDA versions (e.g., 12.6 or 12.9), specific GPU-enabled wheels from the PaddlePaddle repository must be used to ensure compatibility with the GPU driver.[9, 25]

```bash
# Example for CUDA 12.6
python -m pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
``` [25]

## Configuration and Model Management

Post-installation, MinerU requires the presence of several model weights to function. The management of these weights and the system's global configuration is handled through a JSON-based framework.

### The Configuration Shift: magic-pdf.json to mineru.json

Earlier versions of the project (v1.x) utilized a configuration file named `magic-pdf.json`. With the transition to version 2.0 and above, the system now prioritizes `mineru.json`.[24] This file is automatically generated in the user's home directory (e.g., `C:\Users\YourUsername`) the first time the model download utility is run.[8, 10, 18]

Key configuration parameters within `mineru.json` include:
*   **models-dir**: This specifies the absolute path to the directory where model weights are stored. On Windows, it is critical to use forward slashes (e.g., `D:/models`) or escaped backslashes (`D:\\models`) to prevent JSON parsing errors.[26, 27]
*   **device-mode**: Set to `cuda` for GPU acceleration or `cpu` for standard inference.[10, 13]
*   **latex-delimiter-config**: Allows customization of the symbols used to mark LaTeX formulas in the output Markdown.[8, 24]
*   **llm-aided-config**: Configures an external LLM (via OpenAI-compatible API) to assist in determining the title hierarchy and logical structure of the document.[24]

### Automated and Manual Model Acquisition

The system provides a built-in utility, `mineru-models-download`, to facilitate model acquisition. By default, this tool attempts to fetch models from HuggingFace. For users in mainland China or other regions with network restrictions, the model source can be switched to ModelScope.[24, 28]

This change is implemented via an environment variable:
```cmd
set MINERU_MODEL_SOURCE=modelscope
mineru-models-download
``` [24, 28]

If models are moved to a different disk after download, the `models-dir` path in `mineru.json` must be updated accordingly. It is important to note that the `mineru-models-download` tool does not currently support custom download paths; it will always download to a default location and then update the JSON configuration with that path.[28]

## Operational Framework and Usage Scenarios

MinerU provides three primary modes of operation: the Command Line Interface (CLI), the Python API (SDK), and the Web-based User Interface (WebUI).

### Command Line Excellence

The CLI is the primary tool for batch processing and integration into automated shell scripts. The command structure has transitioned from `magic-pdf` in older versions to the unified `mineru` command in version 2.x and later.[5, 8]

**Basic Syntax**:
`mineru -p <input_path> -o <output_path> -m auto` [6, 8]

**Advanced Parameters**:
*   `-m` / `--method`: Determines the parsing logic. `txt` is optimized for text-based PDFs, `ocr` for images and scans, and `auto` allows the system to intelligently switch based on document characteristics.[8, 26]
*   `-b` / `--backend`: Specifies the inference engine, such as `pipeline` or `vlm-transformers`.[8]
*   `-s` / `--start` and `-e` / `--end`: Enables partial parsing of long documents by specifying a range of page numbers (0-indexed).[8]
*   `-f` / `--formula` and `-t` / `--table`: Boolean flags to enable or disable the recognition of mathematical formulas and tables.[8]

### Integration via Python SDK

For sophisticated developers, the Python SDK offers the `Dataset` class, allowing for programmatic control over the parsing stages.[8] This is particularly useful for building custom RAG pipelines where documents need to be processed and then immediately ingested into a vector database. The new `Stage` architecture allows users to define custom processing steps and combine them creatively.[8]

### WebUI and API Services

The project includes a Gradio-based demo for interactive testing. This can be launched by running `python demo.py` from the demo directory or using the `mineru-gradio` command.[3, 24] For production deployments, `mineru-api` provides a FastAPI service that supports both synchronous (`/file_parse`) and asynchronous (`/tasks`) endpoints.[5] Windows users can also integrate MinerU into tools like Dify via its official plugin, which supports both the cloud-hosted API and local deployments.[4]

## Troubleshooting and Issue Mitigation on Windows

The Windows environment introduces specific failure modes that are often absent on Linux. These typically involve DLL dependencies, path handling, and memory management.

### Dependency and DLL Failures

*   **libiomp5md.dll Missing**: This is the Intel OpenMP Runtime library, essential for parallelizing CPU-based computations. This error occurs if the Intel CPU library dependencies are out of sync. Solutions include installing the Intel Fortran runtime or ensuring that the DLL is present in the `System32` directory or the Python environment's library path.[29, 30]
*   **zlib.dll Errors**: A "missing" `zlib.dll` can prevent the application from starting. This is often caused by accidental deletion or incomplete package installation. Reinstalling the program that uses the library or running `sfc /scannow` to repair the Windows system files are common remedies.[31]
*   **ModuleNotFoundError: No module named 'package'**: This deceptive error is often triggered by an incompatible version of the `ultralytics` package. The verified fix is to downgrade `ultralytics` to version 8.3.43 or 8.3.40.[32]

### Path and JSON Parsing Issues

The Windows backslash (`\`) is a frequent source of "Unexpected Token" errors in the JSON configuration files. Because the backslash is an escape character in JSON, it must be escaped with another backslash (e.g., `D:\\MinerU\\models`) or replaced with a forward slash (`D:/MinerU/models`).[26, 27] Furthermore, Windows users with non-ASCII characters or spaces in their usernames (e.g., `C:\Users\User Name`) may encounter issues with the default configuration path. Setting the `MINERU_TOOLS_CONFIG_JSON` environment variable to a custom path on a different drive can bypass these restrictions.[33]

### Optical Character Recognition (OCR) Degradation

In documents with a high density of inline formulas, users may observe that some text lines or symbols are missing from the output. This is often caused by overly aggressive binarization thresholds in the layout detector or OCR engine.[34] Adjusting the `det_db_thresh` and `det_db_box_thresh` parameters in the OCR initialization configuration can mitigate this. Lowering `det_db_box_thresh` from the default 0.6 to 0.3 allows the engine to retain more bounding boxes that might otherwise be filtered out as noise.[34]

## Performance Optimization and Stability

Moving from experimental parsing to production-scale document processing on Windows requires the application of several optimization strategies.

### Memory Optimization for Long Documents

Historically, parsing ultra-long documents (thousands of pages) led to massive memory spikes and eventual crashes. MinerU has addressed this by introducing a "sliding-window" mechanism that processes the document in smaller, manageable chunks.[5]

The parameter `MINERU_PROCESSING_WINDOW_SIZE` (defaulting to 64) can be adjusted via environment variables to fine-tune the memory usage.[35] On systems with limited RAM, reducing this window size ensures stability, while on high-end workstations, increasing it can improve throughput. Additionally, the system now supports streaming writes to disk, allowing results to be persisted as they are completed rather than waiting for the entire document to finish.[5]

### VRAM and GPU Tuning

For users leveraging GPU acceleration, the `MINERU_HYBRID_BATCH_RATIO` environment variable allows for the dynamic adjustment of VRAM usage. This is critical for fitting the VLM and OCR models into consumer-grade GPUs with limited memory.[35]

| Available VRAM | Recommended Batch Ratio |
| :--- | :--- |
| **<= 2 GB** | 1 |
| **<= 3 GB** | 2 |
| **<= 4 GB** | 4 |
| **<= 6 GB** | 8 [35] |

For large-scale deployments, the introduction of `mineru-router` in version 3.0.0 allows for unified entry deployment across multiple services and GPUs. It provides automatic task load balancing and is fully compatible with the standard `mineru-api` interfaces.[5]

## Conclusion and Strategic Outlook

The implementation of MinerU on Windows platforms provides a powerful mechanism for high-precision document extraction, despite the inherent complexity of the installation process. By navigating the nuances of C++ build toolchains, specialized `detectron2` wheels, and CUDA-aligned PaddlePaddle versions, professional users can establish a stable and efficient parsing environment.

The transition toward version 3.0.0 represents a significant milestone in the project's maturity, emphasizing not just raw accuracy but also engineering stability and architectural flexibility. Features like native DOCX parsing and the sliding-window mechanism for long documents demonstrate a commitment to production-readiness. As MinerU continues to integrate with the broader AI ecosystem—serving as a foundational layer for RAG frameworks and agentic platforms—its role in the document intelligence domain is poised to expand significantly. For Windows-based enterprises and researchers, following the structured deployment framework detailed in this report ensures that they can capitalize on these advancements while maintaining the data sovereignty and performance benefits of a local installation.

---

1. MinerU, [https://opendatalab.github.io/MinerU/](https://opendatalab.github.io/MinerU/)
2. papayalove/Magic-PDF - GitHub, [https://github.com/papayalove/Magic-PDF](https://github.com/papayalove/Magic-PDF)
3. Extract Any PDF with MinerU 2.5 (Easy Tutorial) - Sonusahani.com, [https://sonusahani.com/blogs/mineru](https://sonusahani.com/blogs/mineru)
4. MinerU - Dify Marketplace, [https://marketplace.dify.ai/plugin/langgenius/mineru](https://marketplace.dify.ai/plugin/langgenius/mineru)
5. GitHub - opendatalab/MinerU: Transforms complex documents like PDFs into LLM-ready markdown/JSON for your Agentic workflows., [https://github.com/opendatalab/mineru](https://github.com/opendatalab/mineru)
6. Quick Start - MinerU, [https://opendatalab.github.io/MinerU/quick_start/](https://opendatalab.github.io/MinerU/quick_start/)
7. FAQ - MinerU - OpenDataLab | Data-Centric AI Research, [https://opendatalab.github.io/MinerU/faq/](https://opendatalab.github.io/MinerU/faq/)
8. mineru - PyPI, [https://pypi.org/project/mineru/2.0.0/](https://pypi.org/project/mineru/2.0.0/)
9. Install on Windows via PIP-Document-PaddlePaddle Deep Learning Platform, [https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/windows-pip_en.html](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/windows-pip_en.html)
10. Installation - Boost With Cuda - 《MinerU v1.1 Documentation》 - 书栈网 · BookStack, [https://www.bookstack.cn/read/mineru-1.1-en/e60b2c33b3945c15.md](https://www.bookstack.cn/read/mineru-1.1-en/e60b2c33b3945c15.md)
11. [R] Struggle with PaddlePaddle OCR Vision Language installation - Reddit, [https://www.reddit.com/r/MachineLearning/comments/1p5d1gn/r_struggle_with_paddlepaddle_ocr_vision_language/](https://www.reddit.com/r/MachineLearning/comments/1p5d1gn/r_struggle_with_paddlepaddle_ocr_vision_language/)
12. Can't install paddle · PaddlePaddle PaddleOCR · Discussion #14556 - GitHub, [https://github.com/PaddlePaddle/PaddleOCR/discussions/14556](https://github.com/PaddlePaddle/PaddleOCR/discussions/14556)
13. AiBotLab/MinerU - Gitee, [https://gitee.com/yuzhu_yang/MinerU/blob/master/README.md](https://gitee.com/yuzhu_yang/MinerU/blob/master/README.md)
14. Installation Guide-Document-PaddlePaddle Deep Learning Platform, [https://www.paddlepaddle.org.cn/documentation/docs/en/2.2/install/index_en.html](https://www.paddlepaddle.org.cn/documentation/docs/en/2.2/install/index_en.html)
15. Step-by-Step Guide: How to Install Detectron2 from Scratch on Windows - Medium, [https://medium.com/@lukmanshaikh/step-by-step-guide-how-to-install-detectron2-from-scratch-on-windows-748b69cf18f1](https://medium.com/@lukmanshaikh/step-by-step-guide-how-to-install-detectron2-from-scratch-on-windows-748b69cf18f1)
16. How to install Detectron2 on Your Windows local system? - Shreyas Kulkarni, [https://helloshreyas.com/how-to-install-detectron2-on-windows-machine](https://helloshreyas.com/how-to-install-detectron2-on-windows-machine)
17. Detectron 2 Installation on Windows | by Vigneshwara - Medium, [https://medium.com/@rockingstarvic/detectron-2-installation-on-windows-3c8e717b44fd](https://medium.com/@rockingstarvic/detectron-2-installation-on-windows-3c8e717b44fd)
18. magic-pdf - PyPI, [https://pypi.org/project/magic-pdf/](https://pypi.org/project/magic-pdf/)
19. How to install Detectron2 - Stack Overflow, [https://stackoverflow.com/questions/75357936/how-to-install-detectron2](https://stackoverflow.com/questions/75357936/how-to-install-detectron2)
20. fail to install detectron2 · Issue #199 · opendatalab/MinerU - GitHub, [https://github.com/opendatalab/MinerU/issues/199](https://github.com/opendatalab/MinerU/issues/199)
21. Installation — detectron2 0.6 documentation, [https://detectron2.readthedocs.io/tutorials/install.html](https://detectron2.readthedocs.io/tutorials/install.html)
22. Detectron2 & Python Wheels Cache - Medium, [https://medium.com/data-science/detectron2-python-wheels-cache-bfb94a0267ef](https://medium.com/data-science/detectron2-python-wheels-cache-bfb94a0267ef)
23. It is impossible to start magic-pdf --version using the command line, and a TypeError is reported. · Issue #232 · opendatalab/MinerU - GitHub, [https://github.com/opendatalab/MinerU/issues/232](https://github.com/opendatalab/MinerU/issues/232)
24. Quick Usage - MinerU, [https://opendatalab.github.io/MinerU/usage/quick_usage/](https://opendatalab.github.io/MinerU/usage/quick_usage/)
25. Install on Windows via PIP, [https://www.paddlepaddle.org.cn/en/install/quick?docurl=/documentation/docs/en/install/pip/windows-pip_en.html](https://www.paddlepaddle.org.cn/en/install/quick?docurl=/documentation/docs/en/install/pip/windows-pip_en.html)
26. lm_tool/MinerU - Gitee, [https://gitee.com/lm_tool/MinerU/blob/master/README.md](https://gitee.com/lm_tool/MinerU/blob/master/README.md)
27. Error in parsing backslash escape sequence in JSON - Stack Overflow, [https://stackoverflow.com/questions/52343137/error-in-parsing-backslash-escape-sequence-in-json](https://stackoverflow.com/questions/52343137/error-in-parsing-backslash-escape-sequence-in-json)
28. Model Source - MinerU, [https://opendatalab.github.io/MinerU/usage/model_source/](https://opendatalab.github.io/MinerU/usage/model_source/)
29. Libiomp5md.dll Not Found? Here's the Fast Fix! - YouTube, [https://www.youtube.com/watch?v=IltGCJLbW5I](https://www.youtube.com/watch?v=IltGCJLbW5I)
30. Missing DLL problem - CoPS, [https://www.copsmodels.com/gpmissingdll.htm](https://www.copsmodels.com/gpmissingdll.htm)
31. Download.... Missing Zlib.dll from ur computer ?? - Microsoft Q&A, [https://learn.microsoft.com/en-us/answers/questions/2456917/download-missing-zlib-dll-from-ur-computer](https://learn.microsoft.com/en-us/answers/questions/2456917/download-missing-zlib-dll-from-ur-computer)
32. pip installation successful, but 'magic-pdf --version' cannot display the version · Issue #1219 · opendatalab/MinerU - GitHub, [https://github.com/opendatalab/MinerU/issues/1219](https://github.com/opendatalab/MinerU/issues/1219)
33. MinerU customized weight folder · Issue #2955 - GitHub, [https://github.com/opendatalab/MinerU/issues/2955](https://github.com/opendatalab/MinerU/issues/2955)
34. Layout Bug · Issue #450 · opendatalab/MinerU - GitHub, [https://github.com/opendatalab/MinerU/issues/450](https://github.com/opendatalab/MinerU/issues/450)
35. CLI Tools - MinerU, [https://opendatalab.github.io/MinerU/usage/cli_tools/](https://opendatalab.github.io/MinerU/usage/cli_tools/)