## MH1
**类型:** comparison
**问题:** RDK X3 和 RDK X5 的 CPU 核心数和主频分别是多少，有何差异？
**答案:** RDK X3 搭载 4 核 ARM Cortex-A53，主频 1.2GHz；RDK X5 搭载 8 核 ARM Cortex-A55，主频 1.5GHz，X5 核心数翻倍且主频更高。
**Hop1:** hardware / rdk_x3_spec | 提供 RDK X3 的 CPU 规格参数
**Hop2:** hardware / rdk_x5_spec | 提供 RDK X5 的 CPU 规格参数
---

## MH2
**类型:** reasoning
**问题:** 使用 RDK 开发板进行 BPU 推理时，需要先完成哪些环境准备步骤？
**答案:** 需要先完成系统烧录、驱动安装，再配置 Python 环境，最后安装 horizon_bpu 推理库。
**Hop1:** quick_start / system_install | 提供系统烧录和驱动安装步骤
**Hop2:** linux_development / bpu_develop | 提供 BPU 推理环境配置和库安装步骤
---

## MH3
**类型:** aggregation
**问题:** RDK 平台支持哪些多媒体编解码格式，对应的硬件加速模块是什么？
**答案:** 支持 H.264/H.265 编解码，由 VPU 硬件模块加速；支持 JPEG 编解码，由 JPU 模块加速。
**Hop1:** multimedia_development / codec_overview | 提供支持的编解码格式列表
**Hop2:** hardware / hardware_modules | 提供 VPU/JPU 硬件模块说明
---
