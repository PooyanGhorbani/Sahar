# سحر 0.1.74 / Sahar 0.1.74

**پارسی | English | 中文**

Sahar is a Telegram-first Xray / VLESS management platform built around a **Master / Agent** architecture.
It is designed for people who want centralized management, stable subscriptions, guided installation, and optional Cloudflare automation without manually editing many files on each server.

![version](https://img.shields.io/badge/version-0.1.74-8b5cf6)
![platform](https://img.shields.io/badge/linux-Debian%20%7C%20Ubuntu%20%7C%20Alpine-0ea5e9)
![profiles](https://img.shields.io/badge/VLESS-Reality%20%2B%20Simple-22c55e)
![panel](https://img.shields.io/badge/Panel-Telegram-2563eb)

> Supported systems: **Ubuntu / Debian / Alpine**  
> Installer must run with **root** privileges.

---

## Language navigation

[پارسی](#پارسی) | [English](#english) | [中文](#中文)

---

# پارسی

## سحر چیست؟

**سحر** یک سامانه مدیریت Xray / VLESS است که با معماری **Master / Agent** کار می‌کند و مرکز کنترل آن یک **بات تلگرام** است.
هدف پروژه این است که مدیریت کاربران، سرورها، سابسکریپشن‌ها و تغییرات روزانه را از کارهای دستی و پراکنده به یک روند متمرکز، قابل نگهداری و قابل توسعه تبدیل کند.

## قابلیت‌های اصلی

- مدیریت مرکزی با **Master**
- اجرای **Agent** روی هر VPS برای اعمال تغییرات Xray
- پنل مدیریتی از داخل **تلگرام**
- لینک **subscription ثابت** برای هر کاربر
- پشتیبانی از پروفایل‌های **VLESS Simple** و **VLESS Reality**
- خودکارسازی اختیاری **Cloudflare DNS / Tunnel**
- نصب راهنمایی‌شده با اعتبارسنجی ورودی‌ها
- پشتیبانی از **systemd** و **OpenRC**
- کار با **Ubuntu / Debian / Alpine**

## معماری پروژه

### Master
Master هسته‌ی مدیریتی پروژه است و این اجزا را اجرا می‌کند:
- بات تلگرام
- دیتابیس SQLite
- سرویس subscription
- scheduler
- backup manager
- cloudflare manager / bootstrap
- ابزار provisioning از طریق SSH

### Agent
Agent روی هر نود نصب می‌شود و برای این کارها استفاده می‌شود:
- ساخت، حذف و ویرایش کاربر
- فعال و غیرفعال کردن کاربر
- بازخوانی یا ری‌استارت Xray
- گزارش سلامت نود
- هماهنگی با Master

### Telegram Bot
بات تلگرام رابط اصلی مدیریت روزمره است. از داخل آن می‌توانی:
- کاربر بسازی
- پلن را عوض کنی
- لینک یا QR بگیری
- سرور اضافه کنی
- سلامت سرویس‌ها را بررسی کنی
- بعضی عملیات نگهداری را اجرا کنی

## ساختار بسته

این بسته شامل این فایل‌ها و پوشه‌های اصلی است:

- `install.sh` بوت‌استرپ نصب
- `install_master.sh` نصب Master
- `install_agent.sh` نصب Agent
- `sahar-installer.sh` نصب تک‌فایلی برای اجرای مستقیم
- `master_app/` کدهای Master
- `agent_app/` کدهای Agent
- `tests/` تست‌ها
- `VERSION` نسخه بسته

## نصب سریع

### نصب Master از داخل ریپو

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh master'
```

### نصب Agent از داخل ریپو

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh agent'
```

### نصب تک‌فایلی با curl

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) master
```

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) agent
```

## روند نصب Master

در نسخه‌های جدید، نصب Master حالت راهنمایی‌شده دارد.
در ابتدای نصب، کاربر زبان را انتخاب می‌کند و بعد فقط ورودی‌های اصلی را می‌دهد.

ورودی‌های اصلی:
- توکن ربات تلگرام
- توکن API کلودفلر
- دامنه اصلی

نصاب توضیح می‌دهد هر مورد چیست، از کجا باید گرفته شود، و همان لحظه هم صحت آن را بررسی می‌کند.
اگر مقدار اشتباه باشد، همان‌جا پیام واضح می‌دهد.

## ساخت توکن Cloudflare

برای سناریوی خودکارسازی Cloudflare، از **API Token** استفاده کن، نه Global API Key.
حداقل مجوزهای لازم معمولاً این‌ها هستند:

- `Zone / Zone / Read`
- `Zone / DNS / Edit`
- `Account / Cloudflare Tunnel / Edit`

بهتر است token را به همان account و همان zone مورد نیاز محدود کنی.

## رفتار سابسکریپشن

برای هر کاربر یک **subscription token ثابت** ساخته می‌شود.
یعنی:
- لینک اصلی کاربر ثابت می‌ماند
- با اضافه یا حذف شدن سرورها، خود لینک عوض نمی‌شود
- فقط محتوای subscription به‌روزرسانی می‌شود

پروفایل‌های معمول:
- `VLESS | Simple`
- `VLESS | Reality`

## نکته‌های اجرایی

- نصب را با **root** انجام بده
- روی Alpine اگر `bash` نصب نیست، اول آن را نصب کن
- Master مرکز کنترل است؛ Agent فقط روی نودها اجرا می‌شود
- اگر از installer تک‌فایلی استفاده می‌کنی، فایل payload کامل پروژه را extract می‌کند

## عیب‌یابی سریع

- اگر نصب روی اعتبارسنجی Telegram یا Cloudflare گیر کرد، معمولاً مشکل از شبکه، DNS، IPv6 یا دسترسی token است
- اگر Cloudflare خطای `Invalid access token` داد، معمولاً token اشتباه است یا permission لازم را ندارد
- اگر بات کار نمی‌کند، اول `BOT_TOKEN` و اولین چت خصوصی با بات را بررسی کن
- اگر روی Alpine با خطای سرویس یا کاربر مواجه شدی، نسخه‌های جدیدتر installer را استفاده کن

## مناسب چه کسی است؟

این پروژه برای کسانی مناسب است که می‌خواهند:
- چند VPS را از یک نقطه مدیریت کنند
- از پنل وب صرف‌نظر کنند و با تلگرام کار کنند
- لینک subscription ثابت داشته باشند
- نصب و نگهداری را تا حد ممکن خودکار کنند

## لایسنس

این پروژه تحت لایسنس `MIT` منتشر شده است.

---

# English

## What is Sahar?

**Sahar** is an Xray / VLESS management platform built around a **Master / Agent** architecture with a **Telegram-first** control flow.
It is meant for operators who want centralized control, stable user subscriptions, guided installation, and optional Cloudflare automation without manually reconfiguring every server.

## Core capabilities

- Centralized management with a **Master** node
- **Agent** on each VPS for Xray-side changes
- Daily administration through a **Telegram bot**
- Stable per-user **subscription links**
- Support for **VLESS Simple** and **VLESS Reality**
- Optional **Cloudflare DNS / Tunnel** automation
- Guided installer with input validation
- Support for **systemd** and **OpenRC**
- Support for **Ubuntu / Debian / Alpine**

## Architecture

### Master
The Master is the control plane and runs:
- Telegram bot
- SQLite database
- subscription service
- scheduler
- backup manager
- Cloudflare manager / bootstrap logic
- SSH provisioning tools

### Agent
The Agent runs on each node and handles:
- user creation, removal, and updates
- enabling or disabling users
- Xray reload / restart workflows
- node health reporting
- synchronization with the Master

### Telegram Bot
The Telegram bot is the day-to-day operations panel. It is used to:
- create users
- change plans
- fetch links and QR codes
- add servers
- check health
- trigger selected maintenance actions

## Bundle contents

Main files and directories in this package:

- `install.sh` bootstrap installer
- `install_master.sh` Master installer
- `install_agent.sh` Agent installer
- `sahar-installer.sh` stable single-file installer
- `master_app/` Master application code
- `agent_app/` Agent application code
- `tests/` test suite
- `VERSION` package version

## Quick install

### Install Master from the repository

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh master'
```

### Install Agent from the repository

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh agent'
```

### Single-file install with curl

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) master
```

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) agent
```

## Master installation flow

Recent builds use a guided flow.
The installer starts with a language selection screen, then asks only for the main values needed to finish setup.

Primary inputs:
- Telegram bot token
- Cloudflare API token
- root domain

The installer explains what each value is, where to get it, and validates it immediately.
If a value is wrong, the user gets a direct and readable error message.

## Cloudflare token requirements

For automated Cloudflare setup, use an **API Token**, not a Global API Key.
The common minimum permissions are:

- `Zone / Zone / Read`
- `Zone / DNS / Edit`
- `Account / Cloudflare Tunnel / Edit`

It is best to scope the token to the exact account and zone you intend to use.

## Subscription model

Each user receives a **stable subscription token**.
That means:
- the main subscription link does not change
- adding or removing servers updates the content, not the URL
- the user keeps a single stable entry point

Common profiles:
- `VLESS | Simple`
- `VLESS | Reality`

## Operational notes

- Run installation as **root**
- On Alpine, install `bash` first if it does not already exist
- The Master is the control center; Agents run on the managed nodes
- The single-file installer contains the full project payload and extracts it before running

## Quick troubleshooting

- If Telegram or Cloudflare validation hangs or fails, the cause is often networking, DNS, IPv6, or token permissions
- If Cloudflare returns `Invalid access token`, the token is usually wrong or missing required permissions
- If the bot does not respond, verify `BOT_TOKEN` and make sure the first private chat reaches the bot
- If Alpine reports service or user creation issues, use a recent installer build

## Who is this for?

Sahar is a good fit if you want to:
- manage multiple VPS nodes from one place
- work from Telegram instead of a web panel
- keep stable subscription links for users
- automate as much installation and day-to-day maintenance as possible

## License

This project is released under the `MIT` license.

---

# 中文

## Sahar 是什么？

**Sahar** 是一个基于 **Master / Agent** 架构的 Xray / VLESS 管理平台，核心控制方式是 **Telegram**。
它适合希望集中管理节点、用户、订阅，并且希望安装流程清晰、Cloudflare 可选自动化、日常维护尽量减少手工操作的使用者。

## 主要能力

- 通过 **Master** 进行集中管理
- 在每台 VPS 上运行 **Agent** 执行 Xray 侧操作
- 通过 **Telegram 机器人** 完成日常管理
- 为每个用户提供稳定的 **订阅链接**
- 支持 **VLESS Simple** 与 **VLESS Reality**
- 可选的 **Cloudflare DNS / Tunnel** 自动化
- 带输入校验的引导式安装
- 支持 **systemd** 和 **OpenRC**
- 支持 **Ubuntu / Debian / Alpine**

## 架构说明

### Master
Master 是控制中心，负责运行：
- Telegram 机器人
- SQLite 数据库
- subscription 服务
- scheduler
- backup manager
- Cloudflare 管理与初始化逻辑
- SSH provisioning 工具

### Agent
Agent 安装在每个节点上，负责：
- 创建、删除、修改用户
- 启用或禁用用户
- 重新加载或重启 Xray
- 上报节点健康状态
- 与 Master 同步

### Telegram 机器人
Telegram 机器人是日常运维入口，可以用来：
- 创建用户
- 修改套餐
- 获取链接和二维码
- 添加服务器
- 检查健康状态
- 执行部分维护操作

## 包内容

本压缩包主要包含：

- `install.sh` 引导安装脚本
- `install_master.sh` Master 安装脚本
- `install_agent.sh` Agent 安装脚本
- `sahar-installer.sh` 单文件安装脚本
- `master_app/` Master 端代码
- `agent_app/` Agent 端代码
- `tests/` 测试文件
- `VERSION` 版本号

## 快速安装

### 从仓库安装 Master

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh master'
```

### 从仓库安装 Agent

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh agent'
```

### 使用 curl 进行单文件安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) master
```

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PooyanGhorbani/Sahar/main/sahar-installer.sh) agent
```

## Master 安装流程

较新的版本使用引导式安装流程。
安装器会先让用户选择语言，然后只要求输入完成初始化所需的核心信息。

主要输入项：
- Telegram 机器人 Token
- Cloudflare API Token
- 根域名

安装器会说明每个值是什么、应从哪里获取，并在输入后立即校验。
如果填写错误，会直接给出可读性较强的错误提示。

## Cloudflare Token 权限

如果你要启用 Cloudflare 自动化，请使用 **API Token**，不要使用 Global API Key。
常见的最小权限组合为：

- `Zone / Zone / Read`
- `Zone / DNS / Edit`
- `Account / Cloudflare Tunnel / Edit`

建议把 Token 限定到你实际使用的 account 和 zone。

## 订阅模型

每个用户都会获得一个**稳定的订阅 token**。
这意味着：
- 主订阅链接不会频繁变化
- 新增或删除服务器时，只更新内容，不改变 URL
- 用户始终只有一个稳定入口

常见配置类型：
- `VLESS | Simple`
- `VLESS | Reality`

## 运行说明

- 请使用 **root** 进行安装
- Alpine 如果没有 `bash`，请先安装
- Master 是控制中心；Agent 部署在被管理节点上
- 单文件安装器会先解压完整项目内容，再执行对应安装流程

## 快速排错

- 如果 Telegram 或 Cloudflare 校验阶段卡住或失败，通常与网络、DNS、IPv6 或 token 权限有关
- 如果 Cloudflare 返回 `Invalid access token`，通常表示 token 错误或权限不足
- 如果机器人没有响应，请先检查 `BOT_TOKEN`，并确认已经给机器人发送第一条私聊消息
- 如果 Alpine 上出现服务或用户创建问题，请使用较新的安装器版本

## 适合哪些用户？

如果你希望：
- 从一个地方管理多个 VPS 节点
- 使用 Telegram 而不是 Web 面板
- 给用户提供稳定的订阅链接
- 尽量自动化安装和日常维护

那么 Sahar 会比较适合你。

## License

本项目使用 `MIT` 许可证发布。
